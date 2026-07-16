# ADR-0010 — Aislamiento de Memoria por Usuario y Autocrítica Modular

- **Estado:** Aceptado
- **Fecha:** 2026-07-15
- **Relacionado:** ADR-0007 (auditoría IA), ADR-0008 (seguridad enterprise),
  ADR-0009 (Harness Attachments)

## Contexto

El `ContextHarness` de la Fase 11 (ADR-0009) recuperaba memoria semántica
filtrando únicamente por `agente_id`, con una limitación de alcance
documentada explícitamente: "no aísla por usuario todavía". En un sistema
donde varios operadores comparten el mismo agente (p.ej. turnos distintos
en la misma línea de mantenimiento), eso significa que un Operador A podía
recibir en su contexto fragmentos de conversaciones que en realidad tuvo el
Operador B con ese agente — una fuga de información entre roles que el
resto del sistema (RBAC, JWT por usuario, auditoría con `user_id`) ya trata
como dato sensible.

Por otro lado, el `HarnessPort` (ADR-0009) reservaba un hook `post` sin
implementación real: ningún HAT revisaba la respuesta del LLM antes de
entregarla. Eso deja sin cubrir el caso de una respuesta que alucina un
dato o, más grave en un contexto industrial, sugiere saltarse un protocolo
de seguridad (desactivar un interlock, ignorar una parada de emergencia).

## Decisión

### 1. Aislamiento de memoria por `user_id` (fail-closed)

`ContextHarness.apply_hooks("pre", ...)` ahora exige `user_id` en el
contexto. Sin él, **no se hace ninguna consulta** — nunca se degrada a
"buscar solo por agente" como aproximación aceptable. La consulta real
(`audit_service.consultar(agente_id=..., user_id=...)`) queda filtrada por
ambos campos siempre.

`user_id` se enhebra desde el borde HTTP (ya lo traía `OrchestratorService`)
hasta `AgentBase` en las 4 rutas de chat de `core/orchestrator.py`
(`chat_libre`, `chat_con_herramientas` y sus variantes streaming), y de ahí
a `HarnessService.aplicar_pre`. El Guardián (`[DATA-ISOLATION]` en
`scripts/gate.py`) bloquea cualquier consulta a `auditoria_ia` dentro de
`harness_service.py` que no incluya el filtro `user_id=`.

Esto no es aislamiento "por defecto en la práctica" — es una garantía
estructural: el código que consulta memoria semántica no puede compilar/pasar
el gate sin el filtro, y en runtime retorna vacío en vez de arriesgar una
fuga si el `user_id` no llegó.

### 2. CritiqueHarness — autocrítica como post-hook real

Segundo HAT, atachable vía `"harnesses": ["autocritica"]`:

1. Evalúa la respuesta con reglas deterministas (sin llamar al LLM):
   respuesta vacía/insignificante, o coincide con un patrón de la denylist
   de violaciones de seguridad industrial (desactivar interlocks, ignorar
   protocolos, proceder sin autorización, puentear sensores de paro).
2. Si el veredicto es negativo, solicita una **regeneración** — una segunda
   pasada al LLM (`core.providers.generate`) con un prompt correctivo que
   pide una respuesta segura o, si no es posible, que indique que se
   requiere autorización de un supervisor.
3. Si la respuesta regenerada también falla el chequeo (o la regeneración
   no está disponible), se bloquea con un mensaje seguro fijo — la
   respuesta original insegura **nunca** llega al usuario.

Wireado en `core/orchestrator.py` solo en los dos flujos con retorno único
(`chat_libre`, `chat_con_herramientas`): ahí es posible interceptar y
corregir antes de entregar. En los flujos de streaming
(`chat_con_herramientas_stream`, `chat_libre_stream`) los chunks ya salieron
al cliente token a token cuando se conoce la respuesta completa — no hay
forma de "des-enviar" texto ya transmitido, así que CritiqueHarness
**no** se aplica ahí en esta fase. Es una limitación real de la arquitectura
de streaming, no un descuido: corregirla de verdad requeriría buffer del
streaming completo antes de emitir, lo que anula el propósito del streaming.

## Consecuencias

- `HarnessPort.apply_hooks` pasa a ser `async def` (antes sync) — necesario
  para que un HAT pueda volver a llamar al LLM en su hook. `ContextHarness`
  no lo necesitaba pero se ajustó por consistencia de interfaz.
- Costo extra: `autocritica` puede disparar una segunda llamada al LLM por
  respuesta rechazada. Queda fuera de esta fase reflejarlo en
  `auditoria_ia.costo_estimado` (ADR-0007) — pendiente para una fase futura.
- El aislamiento por `user_id` es más estricto que el de `core/memory.py`
  (memoria de sesión, sin partición por usuario) — es una decisión
  deliberada: la memoria de sesión vive solo mientras dura la conversación
  activa, mientras que la memoria semántica persiste indefinidamente en
  `auditoria_ia` y cruza sesiones, por lo que el riesgo de fuga es mayor.
- Activar ambos HATs en un agente real requiere
  `"harnesses": ["memoria", "autocritica"]` en su entrada de `config.json`.
