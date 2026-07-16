# ADR-0011 — Sandbox Docker y Puertos Cognitivos (Speak/Listen)

- **Estado:** Aceptado
- **Fecha:** 2026-07-15
- **Relacionado:** ADR-0007 (auditoría IA), ADR-0009 (Harness Attachments),
  ADR-0010 (aislamiento de memoria), Fase 7 (SubprocessRunner Zero-Trust)

## Contexto

El `SubprocessRunner` (Fase 7) ya garantiza ejecución Zero-Trust para
herramientas: `shell=False`, lista blanca de ejecutables, entorno mínimo sin
API keys. Es suficiente para el único uso real actual (ninguna herramienta
de `core/tools.py` dispara subprocesos hoy — `_calcular` usa un evaluador
AST, no `eval()`). Pero para cargas verdaderamente no confiables (código
generado por el propio LLM, scripts subidos por un usuario) ni siquiera un
entorno mínimo en el mismo proceso/host es garantía suficiente: sigue
compartiendo el kernel, el filesystem y la red del host.

Por otro lado, el encadenamiento de agentes existente (`siguiente_agente_id`)
es estático — se define en `config.json` y corre siempre en el mismo orden
tras completar una tarea. No existe forma de que un agente, EN MEDIO de una
conversación de tool-calling, decida dinámicamente "esto lo sabe mejor otro
agente" y le pida ayuda.

## Decisión

### 1. DockerRunner — sandbox de grado industrial (opcional)

`core/services/sandbox_service.py` gana `DockerRunner`, con la misma forma
de resultado (`ResultadoSandbox`) que `SubprocessRunner` para que sean
intercambiables donde se necesite:

- `--rm` (contenedor efímero, se autodestruye al salir).
- `--network none` (sin red — cero exfiltración de datos vía sockets).
- `--user 65534:65534` (nobody, no-root).
- `--cap-drop ALL` + `--security-opt no-new-privileges`.
- `--memory` / `--memory-swap` iguales (límite duro, sin desbordar a swap) y
  `--cpus` (límite de CPU).
- `--pids-limit 64` (anti fork-bomb).
- `--read-only` + `--tmpfs /tmp:rw,size=64m` (filesystem inmutable, solo
  `/tmp` efímero como scratch).
- **Cero variables de entorno del host propagadas** — nunca se usa `-e`.

Es explícitamente **opcional**: si el binario `docker` no está instalado,
`DockerRunner.ejecutar()` lanza `RuntimeError` con un mensaje claro. Nunca
hace fallback silencioso a ejecución sin aislar, y nunca crashea el proceso
host. `SubprocessRunner` sigue siendo el ejecutor por defecto — `DockerRunner`
es la escalera siguiente cuando el aislamiento a nivel de proceso no basta.

### 2. Puertos Speak/Listen — delegación cognitiva en runtime

`core/ports/cognitive_port.py` define `SpeakPort`/`ListenPort`, implementados
por `core/services/delegation_service.py` (`DelegationService`):

- **Speak**: el agente que delega arma el mensaje, valida que no se esté
  delegando a sí mismo y que el destino exista, y espera la respuesta.
- **Listen**: el agente destino procesa la subtarea con **`chat_libre`**
  (no `chat_con_herramientas`) y responde.

Se expone como una herramienta más de tool-calling —
`consultar_a_otro_agente(agente_id, pregunta)` en `core/tools.py` — así un
agente puede decidir delegar en medio de su propio razonamiento, igual que
decide usar `calcular()` o `buscar_web()`.

**Freno estructural contra ciclos**: el agente delegado responde vía
`chat_libre`, que no tiene tool-calling — no tiene acceso a
`consultar_a_otro_agente` ni a ninguna otra herramienta. Estructuralmente no
puede volver a delegar. No se necesita un contador de profundidad de
delegación: la propia superficie de herramientas disponibles ya lo impide.

**Auditoría de ambos lados**: cada delegación deja DOS trazas en
`auditoria_ia` (tipo `delegacion`) — una con `agente_id` = quien delegó
(`contexto="delegado"`) y otra con `agente_id` = quien resolvió
(`contexto="resuelto"`), ambas con el mismo `user_id` de la conversación
original. Se puede reconstruir la cadena completa de colaboración desde la
auditoría existente sin tablas nuevas.

### 3. Guardián `[TOOL-SECURITY]`

Nueva regla en `scripts/gate.py`: ninguna línea de `core/tools.py` (la
superficie de herramientas expuesta a los agentes) puede acceder a
`os.environ` directamente — eso filtraría API keys y secretos del host al
LLM. Si una herramienta necesita ejecutar algo con variables de sistema,
debe pasar por `sandbox_service.py` (`_entorno_minimo()` /
`DockerRunner`), que construye su propio entorno controlado desde cero.

La regla se acota deliberadamente a `core/tools.py` — los adaptadores
industriales (`core/adapters/*`, ADR-0004) SÍ necesitan leer variables de
entorno legítimas (URLs de broker, credenciales de conexión) para su propia
configuración; eso es un uso distinto y ya cubierto por sus propios tests
(`tests/industrial/`), no por esta regla.

## Consecuencias

- Ningún tool actual de `core/tools.py` usa `os.environ` — la regla arranca
  en verde, sin deuda retroactiva.
- Docker no está instalado en todos los entornos de desarrollo/CI. Los
  tests de `DockerRunner` deben saltarse (skip) con gracia cuando
  `DockerRunner.disponible()` es `False`, en vez de fallar el gate por
  falta de una dependencia externa opcional.
- La regeneración/segunda pasada de `CritiqueHarness` (ADR-0010) y ahora la
  delegación cognitiva comparten un patrón: capacidades que hacen una
  llamada extra al LLM. Sigue pendiente (de una fase futura) reflejar ese
  costo extra en `auditoria_ia.costo_estimado`.
- Activar la delegación no requiere configuración adicional por agente —
  `consultar_a_otro_agente` está disponible para todo agente que use
  tool-calling (Gemini/Groq/OpenAI/DeepSeek), igual que el resto de
  `TOOLS_SCHEMA`.
