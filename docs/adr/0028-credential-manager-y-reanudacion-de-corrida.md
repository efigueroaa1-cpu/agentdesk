# ADR-0028 — Credential Manager del SO y Reanudación de Corrida

- **Estado:** Aceptado
- **Fecha:** 2026-07-30
- **Relacionado:** ADR-0008 (seguridad enterprise y persistencia de secretos,
  origen del vault cifrado que esta decisión antepone), ADR-0013 (persistencia
  dual y esquema gobernado por Alembic, sobre el que se apoya la tabla de
  checkpoint), ADR-0018 (soberanía local: la reanudación es parte de la misma
  garantía de operación sin depender de servicios externos)

## Nota de verdad técnica antes de la decisión

Verificando el código real antes de escribir nada:

- **La refactorización Strangler Fig de `core/api.py` ya estaba hecha.**
  `core/api.py` no existe; es el paquete `core/api/` con un router por dominio
  (`auth_router.py`, `telemetry_router.py`, `agentes_router.py`,
  `sistema_router.py`, `monitor_router.py`, `reportes_router.py`), todos por
  debajo de 500 líneas, más `core/orchestrator/` en el mismo estado (Fase 17,
  ADR-0015). No se tocó — el gate ya lo aprueba.
- **La gestión de secretos NO era solo `.env` en texto plano.** `core/key_vault.py`
  ya cifraba las keys en un vault local (AES-256-GCM con clave ligada a la
  máquina) con `.env`/environ como respaldo. Lo que faltaba era el
  almacenamiento en el gestor de credenciales del SO.
- **No existía ningún mecanismo de checkpoint.** `ejecutar_todos_paralelo`
  corría los 22 agentes sin persistir estados parciales: una interrupción
  perdía todo el progreso del lote.

## Decisión

### 1. `keyring` como almacenamiento primario de secretos

`core/key_vault.py` antepone el **Windows Credential Manager** (vía la librería
`keyring`) al vault cifrado. La prioridad de lectura de `obtener_key()` pasa a
ser:

1. Credential Manager del SO (`keyring`).
2. Vault cifrado local (`.keyvault`).
3. Variable de entorno / `.env` (respaldo secundario).

`guardar_key_cifrada()` escribe en el Credential Manager y en el vault a la
vez, de modo que `migrar_env_a_vault()` (llamado en el arranque de
`core/api/__init__.py`) migra las keys al gestor de credenciales sin cambiar a
sus llamadores. Se añade `AGENTDESK_TAVILY_KEY` a la lista de migración.

`keyring` es **opcional en runtime**: la detección del backend es best-effort y
cacheada (`_keyring()`), y ante su ausencia — build sin la dependencia, entorno
sin sesión de escritorio — la gestión degrada a los niveles 2 y 3 sin
interrumpir el arranque ni el Modo Faena offline. `keyring` y su dependencia
`pywin32-ctypes` entran en `requirements.txt`; el `.spec` declara los
hiddenimports del backend Windows (`keyring.backends.Windows`,
`win32ctypes.core`), que `keyring` resuelve por entry-points en runtime,
invisibles al análisis estático de PyInstaller.

### 2. Reanudación de corrida por checkpoint atómico

Una corrida batch (`ejecutar_todos_paralelo`) que se interrumpe en el agente N
no debe perder los reportes de los agentes 1..N-1. Se añade
`core/repositories/checkpoint_repository.py` con la tabla `checkpoint_corrida`
(clave única `corrida_id + agente_id`, gobernada por Alembic, migración
`b5d2f8a1c0e4`). El modelo vive en el repositorio y no en `core/database.py`
para no crecer ese módulo por encima de su línea base de trinquete.

El motor gana un parámetro opcional `corrida_id`:

- Al iniciar, lee los checkpoints existentes de esa corrida; los agentes ya
  completados se devuelven desde el checkpoint y **no se re-ejecutan**.
- Cada agente que termina con un reporte válido (no `None`, sin `_api_error`)
  persiste su resultado en una única transacción — SQLite y PostgreSQL la
  aplican completa o no la aplican, así que un corte no deja una fila parcial.
  La restricción única hace la escritura idempotente.

Sin `corrida_id` el comportamiento del motor no cambia. `main.py` deriva un
`corrida_id` estable entre reinicios (`hashlib` sobre tarea + ids de agentes +
fecha; no `hash()`, que va salteado por proceso) y limpia el checkpoint cuando
la corrida termina al 100%, para que la siguiente corrida del mismo día
arranque limpia.

### 3. Restricciones de la versión GOLD preservadas

- El watchdog único de 650s (`timeout_tarea_s`, `engine.py`) no se modifica: los
  agentes reanudados desde checkpoint retornan antes de adquirir el semáforo,
  sin pasar por `asyncio.wait_for`.
- El Modo Faena offline (`max_agentes_paralelo=1` automático) no se toca.
- El test `tests/resilience/test_checkpoint_resume.py` queda gateado en
  `check_resiliencia()`.

## Consecuencias

- Los secretos dejan de residir obligatoriamente en un archivo del perfil: en
  Windows viven en el Credential Manager, con el vault cifrado y el `.env` como
  respaldos en ese orden.
- Una corrida de 22 agentes interrumpida (corte de energía, cierre de la app)
  se reanuda desde el último agente completado en vez de reiniciar el lote.
- Verificado con `tests/resilience/test_checkpoint_resume.py`: una corrida con
  un agente que falla deja checkpoint solo del que completó; al relanzarla con
  el mismo `corrida_id`, el agente ya completado no se re-ejecuta y solo corre
  el pendiente; reescribir un checkpoint actualiza la fila sin duplicarla.
