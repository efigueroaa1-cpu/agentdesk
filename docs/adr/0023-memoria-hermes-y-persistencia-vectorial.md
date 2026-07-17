# ADR-0023 — Memoria Hermes: persistencia vectorial local y Libreria de Habilidades

- Estado: Aceptado (2026-07-17, Fase 25)
- Relacionados: ADR-0007 (auditoria_ia), ADR-0009/0010 (HATs y aislamiento),
  ADR-0017 (FinOps IA), ADR-0018 (soberania local / Ollama), ADR-0022
  (integridad de distribucion)

## Contexto

El ContextHarness (ADR-0009) daba "memoria" recalculando TF-IDF en cada
consulta sobre las ultimas trazas de `auditoria_ia`: efimera (nada
persiste como vector), acotada a `CANDIDATOS_MAX=30` trazas, y ciega a
sinonimos (similitud puramente lexica).

Hallazgos de verdad tecnica antes de escribir codigo:

1. **El aislamiento por usuario YA existia y es fail-closed** (ADR-0010):
   ContextHarness exige user_id o no consulta nada. Lo que NO existia era
   el aislamiento por **proyecto** — y `auditoria_ia` no tiene columna de
   proyecto, asi que la dimension proyecto_id nace en el store nuevo, no
   via migracion de la tabla forense.
2. **`auditoria_ia` ya registra las herramientas de cada interaccion**
   (`herramientas_json`, ADR-0007): la Libreria de Habilidades se MINA de
   datos que ya existen — cero captura nueva, cero cambio de esquema.
3. **ChromaDB descartado deliberadamente**: arrastra onnxruntime y un
   arbol de dependencias pesado que es exactamente la clase de fallo
   invisible-a-PyInstaller documentada en la Fase 22 (alembic.ini,
   dialectos por nombre). Para el volumen real de este dominio (miles de
   recuerdos por usuario, no millones) un store SQLite (stdlib) + coseno
   en Python puro es suficiente, medible y empaquetable sin riesgo.
4. **"Similitud semantica profunda" honesta**: sin un modelo de
   embeddings no hay semantica profunda de verdad. El store trabaja en 2
   niveles: `hash-v1` (feature hashing 256-dim + stopwords, determinista,
   offline SIEMPRE) y `ollama:<modelo>` (embeddings densos reales via el
   Ollama local de ADR-0018, `AGENTDESK_OLLAMA_EMBED`). La busqueda solo
   compara vectores del mismo modelo — nunca mezcla espacios vectoriales.

## Decision

### 1. `core/vector_store.py` — VectorStoreHermes

SQLite propio en `%APPDATA%/AgentDesk/db/memoria_vectorial.db` (separado
de la DB principal: la memoria es best-effort y jamas compite con la
transaccionalidad forense). Tabla unica `memoria_vectorial` con scope
`(user_id, proyecto_id, agente_id)` indexado, embedding BLOB float32,
modelo y ts. WAL + lock propio (thread-safe).

**[SEMANTIC-PRIVACY]**: `guardar()` y `buscar()` son keyword-only y
exigen `user_id` y `proyecto_id` — sin scope completo, `ValueError`
(fail-closed). El filtro va en el WHERE de SQL, no en Python post-lectura.
El corte de relevancia es RELATIVO al mejor match (mismo criterio que el
TF-IDF de ADR-0009) para que un recuerdo no relacionado no se cuele por
vocabulario comun.

Siembra: `audit_service.registrar_interaccion()` guarda en Hermes cada
interaccion exitosa (best-effort, mismo principio que Prometheus) con
`proyecto_id` opcional (default `global`).

### 2. ContextHarness sobre Hermes + poda FinOps

El pre-hook consulta PRIMERO Hermes (recuerdos persistentes, con su
antiguedad: "hace N dia(s)") y complementa con el TF-IDF de auditoria
(transicion). Todo pasa por `podar_fragmentos()` (core/embeddings.py):
seleccion greedy por relevancia bajo presupuesto de tokens (~chars/4,
ADR-0007) descartando fragmentos redundantes (Jaccard >= 0.8) — el prompt
solo lleva informacion nueva y relevante.

### 3. `core/services/skill_service.py` — Libreria de Habilidades

- `identificar_secuencias(user_id)`: agrupa interacciones EXITOSAS por su
  secuencia de herramientas; repetirse >= 2 veces = procedimiento, no
  accidente.
- `extraer_habilidad(nombre, user_id)`: congela la secuencia como receta
  JSON en `%APPDATA%/AgentDesk/skills/` (con un ejemplo real) y la indexa
  en Hermes (`tipo="habilidad"`).
- `SkillHarness` (HAT `"habilidades"`): recupera por similitud las
  recetas del usuario relevantes al mensaje y las inyecta como
  procedimiento sugerido — cualquier agente DEL MISMO USUARIO las invoca.
- Endpoints: `GET /skills` y `POST /skills/extraer` (supervisor+, RBAC en
  el handler; el user_id sale del token, jamas del payload).

Las habilidades son know-how del usuario que las aprendio: no se
comparten entre usuarios (misma logica que la memoria, ADR-0010).

### 4. Guardian

- `[SEMANTIC-PRIVACY]`: toda llamada `hermes().buscar()/guardar()` en el
  fuente debe llevar `user_id=` y `proyecto_id=` explicitos en la misma
  llamada (ventana por balance de parentesis), y `_exigir_scope` debe
  seguir aplicado en el store. Defensa en profundidad sobre la firma
  keyword-only.
- `check_memoria_hermes`: la suite `tests/memory/` corre en cada gate.

## Consecuencias

- (+) Criterio de exito verificado por test: un recuerdo sembrado hace 3
  dias sobrevive a un "reinicio" (instancia nueva sobre el mismo archivo)
  y llega al prompt con su antiguedad declarada; usuario B y proyecto B
  reciben exactamente nada.
- (+) FinOps: la poda garantiza presupuesto de tokens y elimina
  redundancia antes de gastar.
- (+) Con Ollama local presente, los embeddings pasan a ser densos sin
  cambiar una linea de codigo cliente (el modelo viaja en cada fila).
- (−) Sin Ollama, la similitud es lexica robusta (hashing + stopwords),
  no semantica profunda — documentado, no maquillado.
- (−) La memoria vectorial no participa de la purga de retencion de
  ADR-0018 (esa cubre `auditoria_ia`); la retencion de Hermes queda como
  deuda declarada para una fase futura.
