# ADR-0003 — Desacoplamiento del Motor de Agentes (Fases 2–4)

- **Estado:** Aceptado
- **Fecha:** 2026-07-14
- **Relacionado:** ADR-0002 (reglas de imports), ADR-0001 (puerto de telemetría)

## Contexto

Tras los cimientos (Fase 0) y la migración de Auth/RBAC (Fase 1), el
"componente Dios" `core/api.py` seguía conteniendo el cerebro operativo de
AgentDesk mezclado con el transporte HTTP: ejecución de tareas con telemetría
y persistencia, chat con tool-calling (normal y SSE), analytics del dashboard,
resúmenes con LLM, generación de PDF de Gantt, ingesta de uploads y comandos
remotos. Un hallazgo clave: `core/orchestrator.py` y `core/pipeline.py` ya
eran puros (no importan FastAPI) — **el acoplamiento real era el inverso**:
la API contenía lógica de negocio que pertenece al motor.

## Decisión

Unificar las Fases 2 (AgentService), 3 (PipelineProcessor) y 4 (Orchestrator)
extrayendo toda la lógica de negocio de `api.py` hacia servicios puros:

| Puerto (`core/ports/`) | Servicio (`core/services/`) | Responsabilidad |
|---|---|---|
| `agent_port.py` | `agent_service.py` | Ciclo de vida de agentes (CRUD, reload, ejecutar-todos) |
| `orchestrator_port.py` | `orchestrator_service.py` | Ejecución de tareas, chat (normal/streaming), comandos remotos |
| `pipeline_port.py` | `pipeline_service.py` | Umbrales de guardrails y de alertas económicas |
| — | `analytics_service.py` | KPIs, tendencias (regresión lineal), stats, logs, embeddings |
| — | `insights_service.py` | Briefing Tavily + resúmenes ejecutivos con LLM |
| — | `gantt_report_service.py` | PDF de Avance de Obra (fpdf) |
| — | `upload_service.py` / `report_service.py` | Ingesta de archivos / localización de reportes |

Principios aplicados (Strangler Fig):

1. **Inyección de runtime:** el orquestador, el CommandBridge y el broadcast
   WebSocket llegan a los servicios como callables (`get_orquestador`,
   `get_bridge`, `broadcast`) cableados por api.py — la dependencia apunta
   siempre adaptador→servicio, nunca al revés.
2. **Streaming sin framework:** `chat_stream` del servicio es un generador
   asíncrono de **eventos dict**; api.py solo los serializa a SSE. El motor
   puede alimentar igual un WebSocket, una cola o un test.
3. **Contrato de errores:** LookupError→404 y ValueError→400 en el borde;
   estados operativos (kill switch, motor apagado) como `{"error": ...}` —
   idéntico al contrato histórico del frontend.
4. `core/orchestrator.py` y `core/pipeline.py` permanecen como motor legado
   puro; los servicios los orquestan. Su partición interna (>500 líneas)
   queda gobernada por el trinquete del Guardián.

## Consecuencias

- `api.py`: 2733 → **<1500 líneas**, adaptador de entrada delgado
  (acumulado desde el inicio de la migración: 2865 → ~1494).
- El cerebro es testeable sin FastAPI ni red: servicios con dependencias
  falsas por constructor + Modo Mock (`AGENTDESK_MODE=mock`).
- Nuevos transportes (CLI, gRPC, cola industrial) reutilizan los mismos
  puertos sin duplicar lógica.
- Cambios de infraestructura (otro framework HTTP, otro broker WS) no tocan
  `core/services/` — el Guardián lo hace cumplir en cada gate.
