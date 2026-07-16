# ADR-0014 — Observabilidad OTEL, Métricas Prometheus y Auditoría IA Forense

- **Estado:** Aceptado
- **Fecha:** 2026-07-15
- **Relacionado:** ADR-0007 (auditoría IA, origen), ADR-0009 (HATs),
  ADR-0010 (aislamiento de memoria), ADR-0013 (persistencia Alembic)

## Nota de verdad técnica antes de la decisión

El pedido de esta fase describía "implementar un servicio que registre...
el Prompt completo, el Contexto recuperado (HATs), el Modelo usado y el
Veredicto de cada Guardrail" como si la auditoría IA no existiera.
Verificando el código real: **la auditoría IA ya existe desde ADR-0007**
(Fase 9) — tabla `auditoria_ia`, `audit_service.registrar_interaccion()`,
endpoints `GET /auditoria/interacciones` y `/auditoria/costos`, panel de
diagnóstico en el frontend. Tampoco se reimplementó nada de eso.

Verificando con más cuidado qué faltaba de verdad:

- El campo `prompt` auditado guarda el **mensaje del usuario**, no el
  contexto semántico que los HATs (ADR-0009) inyectan en el prompt real
  enviado al LLM — se descartaba después de usarse. Gap real.
- `veredicto_guardrail` es un **único valor agregado** por interacción
  (`aprobado`/`abortado_guardrails`/...). Ya existía además una tabla
  separada `guardrail_eventos` (`core/compliance.py`) que registra
  **solo los guardrails que abortan**, no el veredicto de los 4 que se
  evalúan en cada corrida del pipeline (`RecursionGuard`, `ToneGuard`,
  `GroundingGuard`, `LogicIntegrityFilter`). Gap real: nunca se veía el
  trail completo de un guardrail que pasó.
- No existía tracing distribuido (OpenTelemetry) en ningún punto del
  sistema, ni un endpoint `/metrics` en formato Prometheus. Gaps reales,
  cero trabajo previo que duplicar.
- El `user_id` viajaba en texto plano en los logs de aplicación
  (`logger.info(...user_id=%s...)`). Gap real de higiene de PII.

## Decisión

### 1. Tracing con OpenTelemetry (`core/telemetry_otel.py`)

`medir_paso(nombre, **atributos)` — context manager que envuelve un paso
(llamada al LLM, ejecución de herramienta, cada guardrail) en un span OTEL
estándar y en un registro liviano en memoria (`deque(maxlen=200)`).
Instrumentado en:
- `core/orchestrator.py::chat_libre` — spans `llm.generar` /
  `llm.generar.reintento`.
- `core/tools.py::ejecutar_herramienta` — span `tool.ejecutar` (cubre las
  12 herramientas, incluida `consultar_a_otro_agente`, ADR-0011).
- `core/pipeline.py::PipelineProcessor.procesar_con_razon` — un span por
  cada uno de los 4 guardrails (`guardrail.RecursionGuard`,
  `guardrail.ToneGuard`, `guardrail.GroundingGuard`,
  `guardrail.LogicIntegrityFilter`).

Detección dinámica (mismo patrón que `AGENTDESK_DB_URL`, ADR-0005/0013):
sin `AGENTDESK_OTEL_ENDPOINT`, los spans solo alimentan el registro en
memoria (`GET /diagnostico/tracing`) — diagnosticable sin infraestructura
externa. Con la variable definida, exporta también vía OTLP/HTTP a un
Collector real. Best-effort: si `opentelemetry` no está instalado,
`medir_paso` degrada a no-op.

### 2. Métricas Prometheus (`core/metrics_prometheus.py` + `GET /metrics`)

Contador de interacciones (`agentdesk_interacciones_total{tipo,exitoso}`),
histograma de tokens estimados y de duración, y un gauge por proveedor LLM
reflejando el estado del Circuit Breaker (ADR-0006). Se usa `prometheus_client`
directamente (no el exporter OTEL-Prometheus, menos maduro) — dos
librerías enfocadas en su propio trabajo en vez de forzar una sola a
cubrir tracing y métricas por igual.

### 3. Auditoría IA Forense completa

`AuditoriaIA` gana dos columnas (migración Alembic incremental
`e1b1692f52c7`, ADR-0013 en uso real por primera vez):
`contexto_hats` (memoria semántica efectivamente inyectada — capturada
vía un canal lateral `AgentBase.ultimo_contexto_hats`, sin cambiar la
firma de retorno de los métodos de chat) y `guardrails_json` (veredicto de
**cada** guardrail evaluado, no solo el que aborta — capturado vía
`PipelineProcessor.ultimo_veredicto`).

### 4. Higiene de PII en logs

`user_id` se sigue guardando en **texto plano en la base de datos** —lo
necesitan el RBAC y el aislamiento de memoria por usuario de ADR-0010,
que dejarían de funcionar si se hasheara ahí— pero los `logger.info(...)`
de `audit_service` ahora imprimen `_hash_pii(user_id)` (SHA-256 truncado a
12 caracteres), nunca el identificador real. Distinción deliberada: la
base de datos es un almacén controlado con RBAC propio; los logs de
aplicación son más propensos a terminar en un agregador externo menos
controlado.

### 5. Guardián `[OBSERVABILITY]`

Todo servicio o puerto **nuevo** en `core/services/`/`core/ports/` debe
referenciar `telemetry_otel` o `metrics_prometheus`. Los 23 archivos
existentes a la fecha quedan grandfathered — no se instrumentan
retroactivamente en este pase.

## Consecuencias

- Cero cambios de contrato en los endpoints `/auditoria/*` existentes —
  los campos nuevos son aditivos (`to_dict()` los agrega, no reemplaza
  nada).
- `GET /metrics` y `GET /diagnostico/tracing` quedan públicos (sin JWT),
  mismo criterio que el ya existente `GET /diagnostico/llm` — son
  endpoints de solo lectura para observabilidad operativa, no exponen PII.
- No reflejar el costo de la doble llamada al LLM de `CritiqueHarness`
  (ADR-0010) ni de la delegación (ADR-0011) en `costo_estimado` sigue
  pendiente — ahora es más visible gracias a los histogramas de tokens
  por interacción, pero cerrarlo queda para una fase futura.
- No hay un Collector OTEL real disponible en este entorno de desarrollo
  — se verificó el modo en memoria (`GET /diagnostico/tracing`) en vivo;
  la exportación OTLP se probó con el endpoint mockeado, no contra un
  Jaeger/Tempo real.
