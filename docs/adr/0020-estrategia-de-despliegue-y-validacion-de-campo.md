# ADR-0020 — Estrategia de Despliegue en Planta y Validación de Campo

- **Estado:** Aceptado
- **Fecha:** 2026-07-17
- **Relacionado:** ADR-0005/0013 (modo dual SQLite/PostgreSQL y migraciones
  Alembic — la base del procedimiento de migración de este ADR), ADR-0014
  (métricas Prometheus, la fuente de los dashboards), ADR-0016 (Zero-Default,
  reutilizado por el smoke test como handshake de seguridad), ADR-0019
  (Queue Mode/Map-Reduce/resource_guard — lo que este piloto valida en campo)

## Nota de verdad técnica antes de la decisión

Verificación del estado real antes de escribir nada, con tres hallazgos:

1. **El instalador nunca empaquetó las migraciones Alembic.** El pedido
   habla de "evitar fallos de hidden imports" en Celery/Redis/PostgreSQL,
   pero los hiddenimports de PostgreSQL (`psycopg2`,
   `sqlalchemy.dialects.postgresql`) **ya existían desde la Fase 10**
   (commit 494763d) — ahí no había nada que arreglar. El fallo real estaba
   en otra parte: `_aplicar_migraciones()` (`core/database.py`, ADR-0013)
   busca `alembic.ini` y `migrations/` en la raíz del bundle, y
   `agentdesk.spec` no incluía **ninguno de los dos** en `datas` — TODO
   instalador generado desde la Fase 15 degradaba silenciosamente a
   `create_all()` (el fallback best-effort documentado). Para escritorio
   con esquema fresco es invisible; para el piloto PostgreSQL con
   migraciones incrementales entre versiones, es exactamente la pieza que
   no puede faltar.
2. **Celery, redis y paho-mqtt no estaban instalados en la máquina de
   build.** PyInstaller no puede empaquetar lo que no existe en el entorno
   que compila: aunque el spec los hubiera declarado, el bundle saldría sin
   ellos. `requirements.txt` los listaba comentados como "opcionales de
   planta" — válido para desarrollo, pero el equipo de BUILD no es la
   planta: si el instalador debe funcionar contra infra real en el cliente,
   las dependencias del piloto deben estar presentes al compilar. Se
   instalaron y se movieron a una sección obligatoria-para-build.
3. **La latencia Map-Reduce no existía en Prometheus.** Solo vivía como
   spans OTel en memoria (`mapreduce.map`/`mapreduce.reduce`, Fase 21) —
   un dashboard de Grafana no puede leer esa deque. El criterio de éxito
   ("mostrar métricas de orquestación paralela en el endpoint de
   Prometheus") requería primero crear esas métricas.

Limitación honesta de este entorno (misma situación documentada en Fases
13/15): **no hay servidor PostgreSQL, broker MQTT ni Redis reales en la
máquina de desarrollo**. El smoke test se verificó contra puertos realmente
cerrados (comportamiento de red real: `ConnectionRefusedError` del stack
TCP, fail-fast medido) y con la política Zero-Default rechazando
credenciales triviales reales. El "PASS" completo de conectividad solo
puede ocurrir en staging — el script está diseñado para eso, no se fabricó
una demo de conexión exitosa.

## Decisión

### 1. Requisitos mínimos de hardware de planta

Derivados de la operación real del sistema (no de benchmarks sintéticos):
el Circuit Breaker de Concurrencia (ADR-0019) suspende tareas pesadas al
cruzar 90% de CPU o RAM, así que el hardware debe dimensionarse para operar
por debajo de ese umbral en régimen:

| Perfil | CPU | RAM | Disco | Uso |
|---|---|---|---|---|
| **Escritorio** (SQLite, sin workers) | 4 núcleos | 8 GB | 10 GB SSD | Operador único, hasta ~10 agentes |
| **Piloto** (PostgreSQL + Redis local) | 8 núcleos | 16 GB | 50 GB SSD | Planta chica, Map-Reduce ≤ 8 workers |
| **Planta** (PostgreSQL + Redis + N workers Celery) | 16 núcleos | 32 GB | 200 GB SSD (DB en volumen propio) | Telemetría OT continua + analítica pesada |

Reglas operativas: PostgreSQL y Redis en hosts (o al menos volúmenes)
separados del host de la API cuando haya telemetría OT continua; el gauge
`agentdesk_carga_host_pct` sostenido sobre 75% es la señal de subir de
perfil ANTES de que el breaker empiece a rechazar (panel dedicado en el
dashboard de Grafana con umbral visual en 75/90).

### 2. Migración Zero-Downtime SQLite → PostgreSQL

El modo dual (ADR-0005) y Alembic (ADR-0013) ya hacen que **el mismo
binario** opere contra ambos motores con el esquema gobernado por la misma
cadena de revisiones. El procedimiento aprovecha eso:

1. **Preparación (sistema en caliente, sin corte):** provisionar PostgreSQL,
   crear usuario dedicado (la política Zero-Default rechaza credenciales
   triviales en el arranque — no es opcional), y correr
   `python scripts/smoke_test_staging.py --todo-obligatorio` desde el host
   de la API: conectividad, handshake de seguridad y timeouts verificados
   ANTES de tocar nada.
2. **Esquema:** con `AGENTDESK_DB_URL` apuntando al PostgreSQL vacío,
   `alembic upgrade head` (o un arranque efímero del binario, que lo corre
   solo) crea el esquema completo por la cadena de revisiones — idéntico al
   que el instalador crea en SQLite, por construcción.
3. **Copia de datos (ventana de solo-lectura, no de apagado):** se pausa la
   ESCRITURA (kill switch de tareas programadas + aviso de mantenimiento),
   el dashboard sigue sirviendo lecturas desde SQLite. Copia tabla a tabla
   (SQLite → PostgreSQL) con verificación de conteo de filas por tabla al
   final. Con los volúmenes de un piloto (≤ decenas de MB) la ventana es de
   minutos.
4. **Conmutación (el único reinicio):** setear `AGENTDESK_DB_URL` y
   reiniciar el servicio. El arranque valida credenciales (Zero-Default,
   Fail-Hard), hace el ping asyncpg (fail-fast 5s) y aplica migraciones
   pendientes. Un reinicio del backend son segundos, no una migración.
5. **Verificación y retorno:** `GET /health`, `GET /diagnostico/arranque`,
   `GET /auditoria/interacciones` (los datos históricos visibles), smoke
   test de nuevo. **Rollback:** quitar `AGENTDESK_DB_URL` y reiniciar —
   SQLite quedó intacto como estaba en el paso 3; nada lo modificó después
   de la pausa de escritura.

### 3. Dashboards de operación (Grafana)

`deploy/grafana/agentdesk-piloto-dashboard.json` (importable en Grafana
≥10, datasource Prometheus parametrizada): filas de Resource Guard (carga
de host con umbrales 75/90, rechazos del breaker, circuitos LLM),
Map-Reduce (p50/p95 por fase, workers exitosos/fallidos), workers Celery y
FinOps IA. Para alimentarlas se agregaron dos métricas nativas nuevas:
`agentdesk_mapreduce_duracion_segundos` (histograma por fase map/reduce) y
`agentdesk_mapreduce_workers_total` (contador por resultado), registradas
desde `MapReduceService.ejecutar()` — cierra el hallazgo 3.

**Nota honesta sobre Celery:** AgentDesk no re-exporta métricas internas de
Celery. Los paneles de workers consumen las métricas estándar de
`celery-exporter` (proyecto externo que se despliega junto al broker en
staging); sin ese exporter muestran "SIN EXPORTER" — lo cual es en sí una
señal de despliegue incompleto, no un error del dashboard.

### 4. Smoke test de integración real

`scripts/smoke_test_staging.py`: cuatro chequeos con conexiones REALES y
cero mocks — [SEC-DB] handshake de seguridad reutilizando la MISMA
`_validar_db_url()` del Fail-Hard de arranque (no una copia que pueda
divergir); [PG] `asyncpg.connect + SELECT 1` con el mismo timeout de 5s del
arranque, verificando además que el camino de FALLO sea rápido (un fallo
lento = timeout no operando, se reporta como defecto aparte); [MQTT]
CONNACK real vía paho con el mismo contrato `host[:puerto]` del adaptador
de planta; [REDIS] ping vía la MISMA `_broker_disponible()` que decide el
Queue Mode en producción. `--todo-obligatorio` convierte SKIP en fallo para
el pipeline de staging. Verificado en vivo contra puertos cerrados reales:
fail-fast de 2-4s con diagnóstico claro, y rechazo de credenciales
triviales en 0.2s.

### 5. Hardening del instalador

`agentdesk.spec`: (a) `datas` gana `alembic.ini` + `migrations/` — cierra
el hallazgo 1; (b) `hiddenimports` gana el bloque de Queue Mode (`celery`,
`celery.backends.redis`, `kombu.transport.redis`, `billiard`, `vine`,
`redis` — Celery y Kombu cargan backends/transportes por NOMBRE en runtime,
el mismo patrón invisible-a-PyInstaller que el dialecto de SQLAlchemy),
Alembic (`alembic.command/config/runtime.migration/script` — carga env.py
por ruta), `asyncpg`, `psutil`, `prometheus_client` y `paho.mqtt.client`
(si no viaja, `AGENTDESK_MQTT_BROKER` degradaría a simulador EN EL CLIENTE
sin error visible — el peor modo de fallo para un piloto).
`requirements.txt` refleja la nueva sección "Piloto industrial: requeridas
en el equipo de BUILD".

## Consecuencias

- El instalador que reciba el cliente lleva migraciones Alembic reales:
  las actualizaciones de esquema del piloto son incrementales y
  reproducibles, no un `create_all()` silencioso que solo funciona en
  esquemas frescos.
- La decisión SQLite→PostgreSQL deja de ser un salto de fe: hay un
  procedimiento con ventana de solo-lectura de minutos, rollback trivial y
  un smoke test que valida la infraestructura ANTES de conmutar.
- Los operadores del piloto ven la salud del sistema (breaker de
  concurrencia, Map-Reduce, workers, gasto de IA) en Grafana sin acceso a
  logs ni endpoints internos.
- Queda documentado qué debe existir en staging y no viaja en el
  instalador: PostgreSQL, Redis, broker MQTT, Prometheus+Grafana y
  celery-exporter.
- Verificado en vivo (dentro de los límites honestos de esta máquina):
  smoke test contra puertos reales cerrados (fail-fast y diagnósticos),
  rechazo Zero-Default de credenciales triviales, build PyInstaller con el
  spec endurecido y `/metrics` del binario resultante exponiendo las
  métricas de orquestación paralela tras un Map-Reduce real — el criterio
  de éxito de la fase en su parte verificable sin infraestructura externa.
