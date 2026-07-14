# ADR-0007 — Observabilidad y Auditoría IA

- **Estado:** Aceptado
- **Fecha:** 2026-07-14
- **Relacionado:** ADR-0005 (persistencia dual), ADR-0006 (resiliencia)

## Contexto

La infalibilidad es imposible (ADR-0006): los modelos alucinan, los guardrails
abortan y los proveedores fallan. En sectores regulados la pregunta no es
"¿falló?", sino "¿puedes demostrar QUÉ pasó, CUÁNDO, con QUÉ entrada y QUÉ
decidió el sistema?". Optamos por **observabilidad total**: ninguna
interacción de agente ocurre sin dejar traza auditable.

## Decisión

### 1. Auditoría Forense (`core/services/audit_service.py` + tabla `auditoria_ia`)

Cada interacción (chat, chat streaming, ejecución de tarea) registra:

| Campo | Contenido |
|---|---|
| `ts`, `user_id`, `agente_id`, `tipo` | quién, con qué agente, qué clase de interacción |
| `prompt`, `contexto`, `respuesta` | entrada/salida (truncadas a 4000 chars) |
| `modelo`, `proveedor`, `herramientas` | con qué se resolvió (tools invocadas) |
| `costo_estimado` | tokens ≈ caracteres/4 (aprox.; conteo exacto = mejora futura) |
| `veredicto_guardrail` | aprobado / abortado_guardrails / error_api / no_aplica |
| `duracion_s`, `exitoso` | desempeño y resultado |

- Registro **best-effort**: la auditoría jamás rompe la interacción que
  registra (fallo propio → warning y se continúa).
- Persistencia portable SQLite/PostgreSQL (ADR-0005): en planta la traza
  vive en el servidor central.
- Lectura protegida por RBAC: `GET /auditoria/interacciones` y
  `/auditoria/costos` exigen rol supervisor+ (403 con viewer/anónimo).

### 2. Diagnóstico en vivo (Módulo "Diagnóstico", nav ID 10)

- `GET /diagnostico/llm` expone el estado de los Circuit Breakers
  (**OPEN/CLOSED**), fallos consecutivos, latencia promedio/última por
  proveedor (ventana de 20 muestras) y el último error.
- `DiagnosticsPanel.jsx` (lazy, poll 5 s) visualiza la cadena de fallback y
  las trazas de auditoría recientes.
- Nota de contrato de navegación: el pedido decía "Módulo 13", pero el ID 13
  pertenece a Seguridad desde el contrato original — Diagnóstico ocupa el
  **ID 10**, que estaba libre.

## Consecuencias

- Trazabilidad completa de una conversación: quién preguntó, qué agente,
  qué herramientas usó, cuánto costó (tokens) y qué dijeron los guardrails.
- La tabla crece con el uso: política de retención/archivado (p.ej. purga a
  N meses o export a frío) queda como decisión operativa de despliegue.
- El costo por tokens es estimado; integrarlo con el pricing real de cada
  proveedor es el siguiente paso natural del panel de costos.
