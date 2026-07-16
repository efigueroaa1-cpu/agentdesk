# ADR-0017 — Cadena de Fallback LLM, Circuit Breakers y FinOps IA

- **Estado:** Aceptado
- **Fecha:** 2026-07-16
- **Relacionado:** ADR-0006 (resiliencia de inteligencia, origen de la
  cadena y los circuit breakers), ADR-0007/ADR-0014 (auditoría IA),
  ADR-0010 (CritiqueHarness), ADR-0016 (Zero-Default / arranque)

## Nota de verdad técnica antes de la decisión

El pedido de esta fase describía "implementar un orquestador de
proveedores que detecte fallos de API" y "un mecanismo de Circuit Breaker"
como si fueran trabajo nuevo. Verificando el código real antes de escribir
nada: **la cadena de fallback y los circuit breakers ya existen completos
desde la Fase 8** (`core/services/llm_service.py`, ADR-0006) — exactamente
la cascada pedida, `Groq → Gemini → OpenAI → mock`, con `CircuitBreaker`
por proveedor (2 fallos consecutivos abren el circuito, 120s de
enfriamiento, semi-abierto tras el enfriamiento), completamente probada
(`tests/resilience/test_llm_fallback.py`, 6/6) y expuesta en
`GET /diagnostico/llm`.

**El hallazgo real, y el verdadero trabajo de esta fase**, apareció al
verificar quién llama a esa cadena: **nadie del camino real del chat/tarea
de un agente**. `core/orchestrator.py` — `AgentBase.chat_libre()` y
`AgentBase.realizar_tarea()`, los dos métodos que ejecutan CADA interacción
real de un agente — llamaban a `core.providers.generate()` **directo**,
saltándose por completo el circuit breaker y la cadena de fallback. Ante
un 429/503 del proveedor configurado, ambos métodos devolvían un mensaje
estático pidiéndole al usuario que **reconfigure otro proveedor a mano**
en vez de recuperarse solos. La única pieza que sí pasaba por
`llm_service.generar()` era `insights_service.py` (resúmenes del
dashboard) — una superficie secundaria, no el chat/tarea principal. La
infraestructura de resiliencia de la Fase 8 llevaba, en la práctica, desde
entonces sin proteger la mayoría del tráfico real del sistema.

Tampoco existía conteo **exacto** de tokens: `core/providers.py` descartaba
el objeto `usage`/`usage_metadata` que cada SDK (OpenAI, Groq, DeepSeek,
Anthropic, Gemini) devuelve en su respuesta, y `audit_service.py` siempre
usaba la aproximación `chars/4` de la Fase 7 — nunca un dato real,
tampoco distinguido como aproximado.

## Decisión

### 1. Conectar la cadena existente al camino real (el fix central)

`AgentBase.chat_libre()` y `AgentBase.realizar_tarea()` ahora llaman a
`llm_service.generar(prompt, temperatura=..., modelo_preferido=self.modelo)`
en vez de `core.providers.generate()` directo. Se elimina el manejo manual
de 429/503 (detección de substring en el mensaje de excepción + mensaje
estático) — ahora es la cadena la que absorbe el fallo automáticamente.

**`modelo_preferido` (extensión nueva de `LlmService.generar()`):** el
proveedor configurado del agente se intenta **siempre primero** —el
fallback nunca anula la elección explícita del usuario, solo la protege—
y si falla, cae al resto de la cadena estándar (`groq→gemini→openai→mock`,
excluyendo el que ya falló). Si el proveedor preferido no tenía circuito
propio (p. ej. un agente configurado con `anthropic:...`, fuera de la
cadena estándar de 3), se le crea uno nuevo en caliente — también queda
protegido, no solo los 3 de la cadena por defecto.

**`chat_con_herramientas()` (tool-calling nativo)** es un caso especial:
habla directo con el SDK de cada proveedor (Gemini/Groq/OpenAI/DeepSeek)
porque necesita su protocolo propio de `tool_calls`, no el `generar()` de
texto plano de `llm_service`. En vez de reescribir ese loop para pasar por
la cadena (fuera de alcance — cambiaría 4 protocolos de tool-calling
distintos), se conecta al **mismo circuito compartido**: antes de entrar
al loop se consulta `llm_service.disponible(proveedor)` y si está abierto
se salta directo a `chat_libre` (que sí es resiliente); si el loop nativo
falla, se llama a `llm_service.registrar_fallo(proveedor, motivo)` antes
de caer también a `chat_libre`. Esto requirió dos métodos públicos nuevos
en `LlmService` (`disponible()`, `registrar_fallo()`/`registrar_exito()`)
para que un llamador externo pueda leer y alimentar el circuito compartido
sin tocar sus atributos privados.

**Streaming queda fuera a propósito** (`chat_libre_stream`,
`chat_con_herramientas_stream` siguen llamando a `generate_stream`
directo) — mismo tipo de limitación ya documentada en ADR-0010 para el
post-hook de `CritiqueHarness`: una vez que los primeros chunks salieron
al cliente por WebSocket/SSE, no hay forma de "des-enviarlos" si el
proveedor falla a mitad de stream. Resolverlo bien (reintentar solo la
porción no enviada, en otro proveedor, sin duplicar texto) es un problema
de diseño distinto que amerita su propio ADR, no una fase que ya cierra
otras cuatro piezas.

**`CritiqueHarness._regenerar()`** (ADR-0010) también se conecta a
`llm_service.generar()` — es una llamada al LLM como cualquier otra, y el
peor momento para no tener red de fallback es justo cuando se necesita
regenerar una respuesta rechazada.

### 2. FinOps IA: tokens exactos cuando el proveedor los expone

`core/providers.py` gana `generate_con_uso()`, que retorna
`{"texto", "proveedor", "modelo", "tokens_entrada", "tokens_salida",
"tokens_total", "tokens_exactos"}`. Cada función `_gemini`/`_openai`/
`_deepseek`/`_anthropic`/`_groq` ahora también extrae el `usage` real de
la respuesta del SDK (`response.usage.prompt_tokens`/`completion_tokens`
para las APIs compatibles con OpenAI; `response.usage_metadata` para
Gemini; `message.usage.input_tokens`/`output_tokens` para Anthropic). Si
la extracción falla (SDK sin ese campo, o el mock) se degrada a la
estimación histórica `chars/4`, con `tokens_exactos=False` — **nunca se
presenta una estimación como si fuera exacta**. `generate()` (contrato de
solo-texto, usado por el resto del sistema) sigue funcionando idéntico —
internamente llama a `generate_con_uso()` y descarta el resto.

`AuditoriaIA` gana dos columnas (migración Alembic incremental
`a7f3c9d1e825`): `tokens_exactos` (Boolean) y `costo_usd_estimado`
(Float). `audit_service.registrar_interaccion()` acepta `tokens_reales`
(el dict de `generate_con_uso()`/`llm_service.generar()`) y lo usa en vez
de la estimación `chars/4` cuando está disponible. El costo en USD se
calcula con una tabla de tarifas **aproximadas por proveedor**
(`_USD_POR_1K_TOKENS`), documentada explícitamente como estimación de
tablero — los precios reales varían por modelo específico y cambian con
el tiempo; esto informa decisiones de FinOps, no reemplaza la factura real
de cada proveedor.

`AgentBase` gana dos canales laterales más (mismo patrón que
`ultimo_contexto_hats` de ADR-0014): `ultimo_proveedor_llm` (quién
respondió realmente — puede diferir del proveedor configurado si hubo
fallback) y `ultimo_tokens_llm`. `OrchestratorService._auditar()` los lee
vía `getattr` defensivo y los propaga a la traza forense.

`GET /metrics` (Prometheus) gana `agentdesk_tokens_total` (contador por
proveedor, distinguiendo `exacto="true"/"false"`) y
`agentdesk_costo_usd_total` (contador por proveedor) — visibilidad de
gasto en tiempo real sin consultar la base de datos.

### 3. Guardián `[LLM-RESILIENCE]`

`scripts/gate.py` gana `check_llm_resilience()`: bloquea cualquier
`from core.providers import generate` (la palabra exacta, no
`generate_stream` ni `generate_con_uso`) o `providers.generate(` en
`core/` fuera de `core/providers.py` (donde se define) y
`core/services/llm_service.py` (el envoltorio de resiliencia). Es
literalmente la regla que habría bloqueado el hallazgo central de esta
fase si hubiera existido antes — `core/orchestrator.py` habría fallado el
gate desde el día en que se agregó esa llamada directa.

## Consecuencias

- El chat y la ejecución de tareas de **cualquier** agente ahora heredan
  automáticamente el 99.9% de uptime de inteligencia que la Fase 8 diseñó
  pero que, en la práctica, solo protegía al dashboard.
- Un agente configurado con un proveedor que se cae ya no le pide al
  usuario que reconfigure algo a mano — la próxima interacción cae sola al
  siguiente proveedor sano, con el cambio visible en `GET /diagnostico/llm`
  y en cada fila de `auditoria_ia`.
- La auditoría financiera de IA (`GET /auditoria/costos`, `GET /metrics`)
  deja de ser una aproximación uniforme — distingue tokens reales de
  estimados por fila, y agrega un costo USD orientativo por agente/proveedor.
- Streaming sigue siendo el punto ciego documentado de la resiliencia
  cognitiva — cualquier fase futura que lo aborde debería empezar
  releyendo esta sección, no asumir que ya está resuelto.
- Verificado en vivo (`tests/resilience/test_llm_resilience_wired.py`):
  una tarea completa con Groq simulado caído, fallback automático a
  Gemini, y la traza de auditoría resultante con `proveedor="gemini"`,
  `tokens_exactos=True` y `costo_usd_estimado > 0` — el criterio de éxito
  de la fase, de punta a punta, no solo por partes aisladas.
