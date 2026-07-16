# ADR-0018 — Soberanía Local (Ollama), Alertas Activas y Purga de Datos

- **Estado:** Aceptado
- **Fecha:** 2026-07-16
- **Relacionado:** ADR-0006/ADR-0017 (cadena de fallback y circuit breakers,
  origen de la infraestructura que esta fase extiende), ADR-0007/ADR-0014
  (auditoría IA, la tabla que esta fase aprende a purgar), ADR-0013
  (telemetría OTel, la fuente de `spans_recientes` que usan las alertas),
  ADR-0016 (Zero-Default / arranque, el patrón que sigue la configuración
  de retención)

## Nota de verdad técnica antes de la decisión

A diferencia de las Fases 17-19, donde el hallazgo real solía ser "esto ya
existe pero no está conectado", verificando el código real antes de escribir
nada en esta fase se confirmó lo contrario: **las cuatro piezas pedidas son
trabajo genuinamente nuevo**. No existía ningún adaptador Ollama/LM Studio en
`core/providers.py` (el catálogo cubría Groq/Gemini/OpenAI/DeepSeek/Anthropic,
todos con salida a internet), no existía `core/services/alert_service.py`, y
`audit_service.py` no tenía ningún mecanismo de retención — las filas de
`auditoria_ia` se acumulaban indefinidamente. `core/scheduler.py` sí existía,
pero es un motor de tareas específico de monitoreo web (fútbol/energía/
economía) — reutilizarlo para purga/alertas habría forzado dominios
completamente distintos dentro del mismo módulo, así que se optó por loops
de fondo independientes, mismo patrón liviano que ya usa `kill_switch`.

## Decisión

### 1. Soporte de LLM local (Ollama/LM Studio)

`core/providers.py` gana un adaptador `_ollama`/`_ollama_stream` que habla
el protocolo **compatible con la API de OpenAI** que exponen tanto Ollama
como LM Studio (`AsyncOpenAI` apuntando a `AGENTDESK_OLLAMA_BASE_URL`,
default `http://localhost:11434/v1`) — no se escribió un cliente HTTP nuevo
desde cero porque ambos servidores locales ya implementan ese contrato, el
mismo que usan `_openai`/`_deepseek`. `proveedores_configurados()` marca
`ollama` como **siempre configurado** (Zero-Default, ADR-0016): a diferencia
de los proveedores de nube, un servidor local no requiere API key — su
disponibilidad real la determina el circuit breaker en tiempo de ejecución,
no una credencial declarada de antemano.

**Se agrega al final de la cadena real de proveedores**, ANTES del mock:
`Groq → Gemini → OpenAI → Ollama (local) → MockProvider`. Entre "toda la
nube caída" y "degradar a respuestas deterministas sin inteligencia real"
hay un tercer estado que la cadena de la Fase 8/19 no contemplaba: un modelo
local que sigue siendo inteligencia real, solo que sin salir a internet.
`mock` se conserva como último eslabón porque cumple un rol distinto que
Ollama no reemplaza — garantiza respuesta SIEMPRE, incluso sin ningún
servidor local corriendo, y es el determinismo que usa toda la suite de
tests (`AGENTDESK_MODE=mock`).

`CircuitBreaker` (`core/services/llm_service.py`) gana el campo
`abierto_desde`: el instante (`time.monotonic()`) en que empezó la racha
ACTUAL de indisponibilidad continua de un proveedor, reseteado a `0.0` en
cuanto responde con éxito una vez. `abierto_hasta` por sí solo no bastaba
para saber "cuánto lleva caído de verdad": con `ENFRIAMIENTO_S=120` un
circuito nunca muestra más de 2 minutos de ventana cerrada de una sola vez,
aunque sean varios fallos seguidos del mismo problema de fondo arrastrándose
10 minutos. `estado_circuitos()` expone esto como `abierto_desde_hace_s`
para que `alert_service` (y `/diagnostico/llm`) puedan leerlo sin tocar
atributos privados.

### 2. Alertas activas de SLOs industriales

`core/services/alert_service.py` (nuevo) vigila tres SLOs sobre las fuentes
de verdad que YA existían — no duplica datos, solo los interpreta:

- **Latencia p95 > 10s**: percentil sin dependencias externas sobre
  `telemetry_otel.spans_recientes()` filtrado a `nombre == "llm.generar"`.
- **3 fallos consecutivos de guardrails**: las 3 trazas más recientes de
  `audit_service.consultar()` con `veredicto_guardrail == "abortado_guardrails"`.
- **Circuit breaker abierto > 5 minutos**: `abierto_desde_hace_s` de
  `llm_service.estado_circuitos()` comparado contra el umbral.

Cada violación emite `logger.error("AUDITORIA_SEGURIDAD: ...")` — mismo
canal ya usado por el resto del sistema para eventos de seguridad críticos,
así que se integra con cualquier agregador de logs existente sin requerir
infraestructura de alerting nueva. Un loop de fondo (`iniciar_monitor()`,
patrón idéntico a `kill_switch.iniciar_monitor()`) corre los tres chequeos
cada 60s, registrado como `asyncio.create_task()` en
`core/api/__init__.py::startup()`.

### 3. Política de retención y purga

`audit_service.purgar_registros_antiguos(dias=None)` (nuevo) **anonimiza**
las filas de `auditoria_ia` más viejas que N días — no las borra. Es una
decisión deliberada: la fila y sus columnas numéricas (tokens, costo_usd,
veredicto_guardrail, duración, timestamp) siguen existiendo para series
históricas de FinOps/SLO; lo que se purga es el contenido con PII/texto
libre (`prompt`, `respuesta`, `contexto`, `contexto_hats`, `user_id` real).
Esto es también lo que hace verificable la garantía de "sin corromper la
base de datos": el conteo de filas y el esquema de la tabla nunca cambian,
solo el contenido de columnas ya existentes.

`N` es configurable vía `AGENTDESK_AUDITORIA_RETENCION_DIAS` (default 365
días); Zero-Default (ADR-0016) aplica igual que en la Fase 18: la AUSENCIA
de la variable es válida (usa el default razonable para sectores regulados),
un valor presente pero inválido (no-entero, `<= 0`) se degrada al default
con una advertencia — nunca lanza una excepción que tumbe la purga. Un loop
de fondo (`iniciar_monitor_purga()`, mismo patrón que `alert_service`) corre
la purga una vez al día, registrado también en `startup()`. La purga
también puede invocarse manualmente llamando a
`audit_service.purgar_registros_antiguos()` directamente (el criterio de
éxito de esta fase pide demostrar precisamente eso).

### 4. Guardián `[DATA-HYGIENE]`

`scripts/gate.py` gana `check_data_hygiene()`: verifica que
`core/api/__init__.py` importe y arranque `audit_service.iniciar_monitor_purga`
como `asyncio.create_task()` real en el arranque del servidor — mismo
patrón de riesgo que `[BOOT-VALIDATION]` (ADR-0016): una política de
retención que existe como función pero nunca se registra como tarea de
fondo queda "instalada" pero inerte, y ningún test de la suite ejercita el
arranque real para detectarlo.

## Consecuencias

- Un despliegue sin conectividad a internet (aislado, on-premise, o
  simplemente con las tres nubes caídas a la vez) sigue teniendo
  inteligencia real disponible mientras un servidor Ollama/LM Studio local
  esté corriendo — la promesa de soberanía de datos deja de depender de que
  la nube esté disponible.
- Las violaciones de SLO ya no requieren que un operador abra un dashboard
  para notarlas — quedan en el mismo canal `AUDITORIA_SEGURIDAD` que ya se
  audita en sectores regulados.
- La tabla `auditoria_ia` deja de crecer indefinidamente con PII en texto
  plano — cumple con políticas de retención de datos sin perder el valor
  histórico agregado (tokens, costos, veredictos) que necesita FinOps/SLO.
- Verificado en vivo:
  - `tests/resilience/test_data_sovereignty.py`: una tarea completa con
    Groq, Gemini Y OpenAI simulados caídos (sin internet), fallback
    automático hasta Ollama local, y la traza de auditoría resultante con
    `proveedor="ollama"` — el primer criterio de éxito de la fase, de punta
    a punta.
  - `tests/audit/test_data_retention.py`: una purga manual sobre una base
    con filas viejas y recientes mezcladas, verificando que el conteo de
    filas de `auditoria_ia` es IDÉNTICO antes y después (integridad), que
    las filas viejas quedan anonimizadas y las recientes intactas, y que
    correr la purga dos veces seguidas es idempotente — el segundo criterio
    de éxito de la fase.
