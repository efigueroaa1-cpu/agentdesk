# ADR-0013 — Persistencia Industrial: Alembic sobre el Modo Dual PostgreSQL/SQLite

- **Estado:** Aceptado
- **Fecha:** 2026-07-15
- **Relacionado:** ADR-0005 (persistencia dual, origen), ADR-0007
  (auditoría IA), ADR-0012 (resiliencia OT)

## Nota de verdad técnica antes de la decisión

El pedido de esta fase describía "implementar en `core/database.py` el
soporte para PostgreSQL" y "detección dinámica de `AGENTDESK_DB_URL`" como
si fuera trabajo nuevo. Verificando el código real antes de escribir nada:
**el modo dual ya existe, completo y probado, desde ADR-0005** (commit
`f807630`) — detección de `AGENTDESK_DB_URL`, motor PostgreSQL con
`pool_pre_ping`/`pool_size=10`/`max_overflow=20` para concurrencia de
planta, fallback a SQLite con WAL en el data dir del usuario. No se
reimplementó nada de eso.

Lo que sí faltaba, verificado en el repo:

- **Alembic no estaba instalado ni configurado.** El esquema se creaba con
  `Base.metadata.create_all(_engine)` — funciona para crear tablas nuevas,
  pero no versiona cambios ni permite migraciones incrementales
  reproducibles entre el instalador de escritorio y una base de producción
  (el pedido explícito de esta fase).
- El motor PostgreSQL usa `psycopg2` (driver **síncrono**) — no `asyncpg`.
  Migrar toda la capa ORM a async habría significado reescribir cada
  `with get_session() as s:` de `core/services/` y `core/repositories/`
  (auditoría, refresh tokens, ejecuciones, backups, ~15 archivos) — una
  reescritura estructural completa, desproporcionada para esta fase y con
  alto riesgo de regresión sobre una suite de tests ya extensa. Se optó por
  **no** hacerlo.

## Decisión

### 1. Alembic gobierna el esquema (ambos motores)

`migrations/env.py` resuelve la URL con la MISMA prioridad que
`core/database.py::init_db()`: override explícito (tests con `db_path`) →
`AGENTDESK_DB_URL` → SQLite del data dir. `init_db()` ahora llama a
`alembic upgrade head` en vez de `create_all()` directo — reproducible e
incremental, igual para SQLite de escritorio que para PostgreSQL de planta.
Revisión base (`c403b23afae5`) generada por autogenerate contra un motor
vacío, reflejando las 10 tablas reales existentes.

**Respaldo best-effort**: si Alembic no está disponible (no instalado, o
`migrations/` no empaquetada en un build futuro), `_aplicar_migraciones()`
degrada a `Base.metadata.create_all()` con un aviso claro — nunca bloquea
el arranque.

### 2. asyncpg — chequeo de arranque, no reescritura del ORM

Alcance deliberadamente acotado: `_verificar_conexion_async()` usa
`asyncpg.connect()` para un ping rápido (timeout 5s) al servidor
PostgreSQL **antes** de construir el engine síncrono. Si el servidor no
responde, falla con un `ConnectionError` claro y las credenciales
redactadas — en vez de que el primer `INSERT` bloqueante del engine
síncrono se cuelgue con un traceback confuso. La capa ORM (sesiones,
queries, commits) sigue siendo síncrona sobre `psycopg2`, como el resto
del sistema. `asyncpg` queda como dependencia opcional de planta (igual
que `psycopg2-binary`) — si no está instalado, el chequeo se omite con un
aviso y el engine síncrono igual intenta conectar.

### 3. Guardián `[DB-CONCURRENCY]`

Nueva regla: ningún adaptador de telemetría (`core/adapters/base.py` y los
tres adaptadores de protocolo) puede llamar `get_session()`/`Session()`
directamente. La telemetría corre en el mismo event loop que el resto del
sistema — una consulta síncrona ahí frenaría TODA la telemetría de planta,
no solo esa lectura. Arranca en verde: ningún adaptador toca la DB
directamente hoy (se apoyan en `ReactorIndustrial` para delegar acciones).

## Consecuencias

- No hay servidor PostgreSQL real disponible en este entorno de
  desarrollo (sin Docker, sin instancia local) — no se pudo demostrar una
  conexión PostgreSQL exitosa en vivo. Se verificó el camino real de fallo
  rápido (`ConnectionError` en <5s, sin colgar el arranque) y el camino de
  éxito con `asyncpg.connect` mockeado — documentado honestamente en
  `tests/persistence/test_dual_mode.py`, sin fabricar una demo falsa.
- Cualquier cambio futuro de esquema debe generarse con
  `alembic revision --autogenerate -m "..."` contra un motor vacío, nunca
  editando `Base` y esperando que `create_all()` lo propague solo.
- Empaquetar `migrations/` + `alembic.ini` en el instalador de escritorio
  (PyInstaller `datas`) queda pendiente de una fase futura — esta fase
  cubre el arranque desde código fuente (dev y despliegue de planta
  ejecutado con Python directo), que es lo que exige el criterio de éxito.
