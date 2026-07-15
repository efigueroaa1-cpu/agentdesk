# ADR-0009 — Harness Attachments (HATs): Memoria Semántica y Autocrítica Modular

- **Estado:** Propuesto (apertura de Fase 11 — sin código todavía)
- **Fecha:** 2026-07-15
- **Relacionado:** ADR-0003 (desacoplamiento del motor de agentes), ADR-0007
  (auditoría IA), ADR-0008 (seguridad enterprise)

## Contexto

Cada agente en AgentDesk ejecuta hoy con las mismas capacidades fijas: llama
al `llm_service` (ADR-0006), sus interacciones quedan auditadas (ADR-0007) y
corre bajo el mismo orquestador para todos. No existe forma de dotar a un
agente puntual de capacidades extra — recordar contexto entre tareas
(memoria semántica) o revisar su propia respuesta antes de entregarla
(autocrítica) — sin tocar el núcleo del orquestador para todos los agentes
por igual.

Ya hubo un intento fallido de este concepto: en la Fase 10 apareció en
`core/orchestrator.py` un campo `self.harnesses` sin uso real ni ADR que lo
respaldara, y se eliminó como código muerto (ver progress.md, cierre de
Fase 10). Este ADR reemplaza esa idea exploratoria por un diseño real antes
de escribir una sola línea de implementación.

## Decisión

**HATs (Harness Attachments):** capacidades componibles que se atachan a un
agente por configuración, no por herencia ni por flag global.

### 1. Configuración por agente

```json
{ "id": "agente.mantenimiento", "harnesses": ["memoria", "autocritica"] }
```

Lista vacía u omitida por defecto — ningún agente existente cambia de
comportamiento sin configuración explícita (compatibilidad hacia atrás sin
shims: es simplemente el valor por defecto).

### 2. Puerto e interfaz

`core/ports/harness_port.py` — interfaz mínima que cualquier harness
implementa:

- `antes_de_ejecutar(contexto) -> contexto`: puede enriquecer el prompt
  (p.ej. memoria inyecta recuerdos relevantes).
- `despues_de_ejecutar(contexto, respuesta) -> respuesta`: puede revisar o
  corregir la salida (p.ej. autocrítica).

Ambos hooks son best-effort: un harness que falla se loguea y se ignora,
igual que `audit_service` (ADR-0007) — nunca rompe la interacción del
usuario.

### 3. Servicio y resolución

`core/services/harness_service.py` resuelve los nombres de `harnesses` del
config del agente a instancias concretas y expone `aplicar_antes` /
`aplicar_despues`. El orquestador (`core/orchestrator.py`) los invoca
alrededor de la llamada al LLM existente — sin acoplar el orquestador a la
implementación de cada harness (regla de imports hexagonal, ADR-0002).

### 4. Los dos harnesses iniciales

| Harness | Qué hace | Se apoya en |
|---|---|---|
| `memoria` | Antes de ejecutar, busca interacciones pasadas semánticamente similares (embeddings ya usados en `embeddings_3d`) y las inyecta como contexto | Infra de embeddings existente — sin nuevo almacén |
| `autocritica` | Después de ejecutar, una segunda pasada por `llm_service` evalúa la respuesta contra los guardrails del agente antes de entregarla | `llm_service` (ADR-0006), mismo circuit breaker/fallback |

Ninguno de los dos requiere infraestructura nueva: ambos reutilizan puertos
que ya existen, solo agregan una capa de orquestación opcional.

## Consecuencias

- Ningún agente actual cambia de comportamiento hasta que se le agregue
  `harnesses` en su configuración.
- Costo extra explícito: `autocritica` implica una llamada adicional al LLM
  por tarea — debe quedar reflejado en `auditoria_ia` (costo_estimado,
  ADR-0007) para que sea visible, no un gasto oculto.
- El fallo de un harness nunca debe bloquear la ejecución del agente
  (best-effort), consistente con el resto del sistema de auditoría.
- Este ADR es el punto de partida de la Fase 11; la implementación real
  (puerto, servicio, tests, guardián si aplica) se documenta en
  `progress.md` a medida que se construye, no se asume aquí.
