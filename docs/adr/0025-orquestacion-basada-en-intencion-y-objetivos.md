# ADR-0025 — Orquestacion basada en Intencion y Objetivos (Copiloto)

- Estado: Aceptado (2026-07-17, Fase 27)
- Relacionados: ADR-0017 (cadena LLM resiliente), ADR-0021 (Curva S/EVM),
  ADR-0022 (firma de codigo), ADR-0023 (Hermes/habilidades), ADR-0024
  (Human-in-the-loop OT)

## Contexto

Toda la potencia acumulada (agentes, habilidades, Gemelo Digital,
actuadores con aprobacion) exigia conocer los modulos: la UX era de
experto. El Copiloto de Intencion la vuelve operable en lenguaje natural.

Hallazgos de verdad tecnica:

1. **Todo el pipeline ya existia por piezas**: habilidades recuperables
   por similitud (ADR-0023), filtro determinista de limites y bandeja de
   aprobacion (ADR-0024), MotorGantt con CPM y Curva S EVM (Sprint 8 /
   ADR-0021), cadena LLM con fallback (ADR-0017). El Intent Engine es
   ORQUESTACION de piezas probadas, no capacidades nuevas — por eso cabe
   en un servicio de ~250 lineas.
2. **El LLM no puede ser el guardian de si mismo**: en modo mock/offline
   no emite JSON valido, y con red puede alucinar valores. El motor trata
   la salida del LLM como BORRADOR: parse robusto, fallback determinista
   por reglas (el copiloto nunca queda mudo), y CERO acciones OT llegan
   al usuario sin pasar `ot_service.validar()` (limites fisicos, Fase 26).
3. **SmartScreen (pendiente F24)**: la advertencia solo la elimina un
   certificado EV (inmediato) u OV (reputacion gradual). Ningun script
   puede eliminarla sin ese certificado — lo que SI se puede dejar
   resuelto es el pipeline completo de firma+verificacion, probado con un
   certificado efimero, para que el certificado real sea solo una env var.

## Decision

### 1. Intent Engine (`core/services/intent_service.py`)

`planificar(objetivo, user_id, proyecto_id)`:

1. Recupera de Hermes las HABILIDADES del usuario relevantes al objetivo
   (scope user_id+proyecto_id, SEMANTIC-PRIVACY intacto).
2. Pide el borrador del plan a la cadena LLM (prompt con el catalogo de
   actuadores y sus limites). Si no hay JSON valido: planificador por
   REGLAS (diagnostico → habilidades aplicables → evaluacion de
   actuadores mencionados → verificacion), determinista y offline.
3. **[INTENT-SAFETY]**: toda accion OT candidata (venga del LLM o de una
   habilidad) pasa por `ot_service.validar()`. Las inseguras van a
   `descartadas_por_filtro` con su motivo — visibles como descartadas,
   jamas ofrecidas como opcion.
4. El plan queda en la auditoria forense (`copiloto_plan`).

`aplicar_en_gantt(plan, proyecto_id)`: inserta las tareas en el Gantt P6
encadenadas Fin→Inicio (CPM recalculado por MotorGantt) y reporta el
impacto en la Curva S (KPIs EVM antes vs despues). Las acciones OT se
PROPONEN a la bandeja de ADR-0024 — el Copiloto nunca ejecuta.

Endpoints `POST /copiloto/planificar` y `POST /copiloto/aplicar`
(supervisor+, RBAC en el handler). UI: modulo "Copiloto" (nav ID 17) —
objetivo en texto libre, plan renderizado, "Aplicar en Gantt P6" con un
clic, acciones OT siempre rotuladas como pendientes de aprobacion.

### 2. Firma de release (`scripts/sign_release.ps1`)

Firma SHA256 + timestamp RFC3161 del instalador (o artefacto indicado),
verificacion con `signtool verify /pa`, y modo `-SelfSignedTest` que
genera un certificado efimero, firma, verifica la integridad del hash y
limpia — valida el PIPELINE de punta a punta sin certificado comprado.
La verdad tecnica sobre SmartScreen queda documentada en el propio
script: EV = reputacion inmediata, OV = gradual, self-signed = nunca.

### 3. Guardian [INTENT-SAFETY]

- `intent_service.py` no puede contener `escribir_tag` ni `.aprobar(` —
  el Copiloto propone, jamas ejecuta.
- Debe usar `ot_service.validar()` y `planificar()` debe pasar por
  `_filtrar_acciones_ot()`.
- La suite `tests/intent/` corre en cada gate.

## Consecuencias

- (+) Criterio de exito por test: peticion en lenguaje natural → plan con
  accion OT validada + tareas reales en el Gantt con impacto en Curva S,
  sin una linea de codigo del usuario; la accion OT queda PENDIENTE y
  cero escrituras ocurren hasta la aprobacion del operador.
- (+) Sin LLM el sistema degrada a plan por reglas — nunca mudo, y sin
  acciones inventadas (solo las de habilidades o ninguna).
- (−) El plan por reglas es deliberadamente conservador; la calidad del
  plan rico depende del LLM disponible. Decision: mejor un plan corto y
  seguro que uno creativo sin filtro.
- (−) SmartScreen desaparece SOLO al configurar el certificado EV/OV real
  (AGENTDESK_SIGN_CERT) — la infraestructura queda lista y probada.
