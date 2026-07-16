# ADR-0019 — Escalabilidad Enterprise: Queue Mode, Map-Reduce y Circuit Breaker de Concurrencia

- **Estado:** Aceptado
- **Fecha:** 2026-07-16
- **Relacionado:** ADR-0006 (Queue Mode original: LocalQueueService/
  CeleryQueueService, Fase 8), ADR-0011 (delegación Speak/Listen 1:1, el
  precedente estructural del que el Map-Reduce de esta fase se diferencia),
  ADR-0017/ADR-0018 (Circuit Breaker de proveedor LLM y de host,
  respectivamente — el mismo patrón aplicado a un recurso distinto)

## Nota de verdad técnica antes de la decisión

El pedido de esta fase describía "implementar un adaptador opcional" de
Celery+Redis como si la infraestructura de Queue Mode fuera trabajo nuevo.
Verificando el código real antes de escribir nada: **`core/services/
queue_service.py` ya implementa el modo dual completo desde la Fase 8**
(`LocalQueueService` sobre `ThreadPoolExecutor` + `CeleryQueueService` sobre
Celery/Redis, con `crear_queue_service()` detectando `AGENTDESK_QUEUE_URL` y
cayendo a modo local si Celery no está instalado o el broker falla). Cero
reimplementación ahí — sería duplicar y arriesgar romper una pieza ya
probada (`tests/resilience/test_queue_service.py`).

**El hallazgo real** apareció al leer `crear_queue_service()` con cuidado:
la "detección automática de broker disponible" que pide esta fase **no era
del todo cierta**. El cliente `Celery(broker=url, ...)` es **lazy** — no abre
ninguna conexión al construirse, solo al despachar la primera tarea real.
Eso significa que, antes de esta fase, con un Redis apagado el sistema
quedaba "en modo distribuido" sin saberlo hasta el primer `encolar()` real
en producción, momento en que recién aparecería el error. La frase "detectar
automáticamente si un broker está disponible" no era literalmente cierta
hasta que se agregó una verificación eager.

Segundo hallazgo: **el trabajo pesado de los agentes (`realizar_tarea`,
generación de reportes) nunca pasaba por `queue_service`** — corría
enteramente dentro del event loop vía `asyncio`, sin ThreadPoolExecutor ni
Celery de por medio. Mismo patrón de "infraestructura de resiliencia
existente pero desconectada del tráfico real" que ya se documentó en
ADR-0017 (Fase 19) para la cadena de fallback LLM — aquí aplicado a
escalabilidad en vez de resiliencia.

Tercer hallazgo: no existía ninguna forma de que un agente 'Líder'
despachara trabajo a N agentes en paralelo. `DelegationService` (ADR-0011)
es Speak/Listen **1:1** — y estructuralmente no puede ser 1:N, porque el
agente delegado responde vía `chat_libre` sin acceso a herramientas
(incluida la que permitiría re-delegar), que es precisamente el freno
anti-ciclos del diseño original. Map-Reduce es una capacidad genuinamente
nueva, no una extensión de Speak/Listen.

## Decisión

### 1. Detección real de broker (cierra el gap de Queue Mode)

`core/services/queue_service.py` gana `_broker_disponible(url) -> bool`:
un PING real al broker (`redis.Redis.from_url(url, socket_connect_timeout=2,
socket_timeout=2).ping()`), con timeout corto y degradación best-effort si
el paquete `redis` no está instalado. `crear_queue_service()` ahora solo
intenta construir `CeleryQueueService` si ese ping responde — la frase
"detecta automáticamente si un broker está disponible" pasa de ser una
esperanza sobre el comportamiento lazy de Celery a una verificación
explícita y verificable.

### 2. Circuit Breaker de Concurrencia (protege el host, no un proveedor)

`core/services/resource_guard.py` (nuevo): `puede_admitir_tarea()` lee la
carga real de CPU/RAM del proceso host vía `psutil` (`AGENTDESK_CPU_MAX_PCT`/
`AGENTDESK_MEM_MAX_PCT`, default 90%/90%, Zero-Default — ausencia válida,
valor inválido degrada con aviso) y rechaza nuevas tareas pesadas si el host
ya está sobre el umbral crítico. `LocalQueueService.ejecutar_pesado()` y
`.encolar()` lo consultan antes de despachar: `ejecutar_pesado` reintenta
brevemente (3 intentos, 0.3s) antes de lanzar `RecursosAgotadosError`;
`encolar()` marca el job como `rechazado_por_carga` sin llegar a
`self._pool.submit()`. Se aplica **siempre**, incluso en modo Celery, porque
`ejecutar_pesado()` corre en el pool local del proceso API sin importar el
modo de `encolar()` — el host que hay que proteger es siempre el mismo.
Sin `psutil` instalado, degrada a "siempre admite" con un aviso único (no
tumba el sistema por una dependencia opcional ausente).

### 3. Orquestación Paralela Map-Reduce

`core/services/map_reduce_service.py` (nuevo): un agente 'Líder' despacha la
misma tarea a N agentes 'trabajadores'. Decisión de diseño central: cada
trabajador corre en su **propio hilo del pool de `queue_service`**
(`ejecutar_pesado(_ejecutar_subtarea_en_hilo, ...)` por cada uno, todos
despachados en paralelo y esperados con `asyncio.gather`), no como
corutinas de `asyncio.gather` compartiendo el hilo del event loop. Dos
razones: (a) aislamiento de fallos real — un worker que revienta no puede
tumbar ni bloquear a los demás ni al loop principal; (b) el Circuit Breaker
de Concurrencia de la sección 2 protege automáticamente CUALQUIER
Map-Reduce, sin código de límite adicional, porque cada worker pasa por el
mismo `ejecutar_pesado()` que ya protege un PDF pesado. Dentro de cada hilo,
`asyncio.run()` crea un event loop propio para poder invocar `chat_libre`
(async) — aislamiento real de SO, no una ilusión de paralelismo.

La fase Reduce (`_reducir_resultados`) consolida: cuenta éxitos/fallos,
concatena las respuestas de los workers exitosos, y expone `hilos_usados`
(nombres de hilo distintos) como evidencia verificable de que el Map corrió
en workers realmente aislados, no en el mismo hilo repetido. Auditado como
un tipo nuevo (`tipo="map_reduce"`) en `auditoria_ia`. Expuesto en
`POST /orquestador/mapreduce` (rol supervisor+, dispara N llamadas reales a
LLM).

### 4. Guardián `[SCALE-LIMITS]`

`scripts/gate.py` gana `check_scale_limits()`: toda función pesada que ya se
despacha vía `queue_service.ejecutar_pesado()`/`encolar()` (la misma lista
de nombres que `[PESADO]`/`check_pesado_sincrono` vigila del lado del
llamador — `generar_pdf_gantt`, `embeddings_3d`, `crear_backup`,
`generar_pdf`, más la nueva `_reducir_resultados`) debe llevar el decorador
declarativo `@costo_recursos(cpu=..., memoria=...)`
(`core/services/resource_guard.py`) inmediatamente antes de su `def`. Es
metadata, no un límite — documenta en el propio código cuánto CPU/RAM
planificar antes de escalar esa tarea a workers Celery reales en producción.

## Consecuencias

- Un despliegue con `AGENTDESK_QUEUE_URL` apuntando a un Redis apagado ya no
  queda "creyéndose distribuido" hasta el primer fallo real en producción —
  se detecta y se degrada a modo local en el arranque.
- El host que corre la API queda protegido de saturación por trabajo pesado
  concurrente (PDFs, embeddings, Map-Reduce) de la misma forma sistemática
  en que ADR-0017 protege contra un proveedor LLM caído — un límite dinámico
  basado en carga real, no un contador fijo arbitrario.
- Un 'Líder' puede repartir análisis de grandes volúmenes de datos
  industriales entre N agentes en paralelo con aislamiento de fallos real,
  sin bloquear el resto del sistema — capacidad que antes no existía en
  ninguna forma (Speak/Listen es 1:1 por diseño).
- Toda función pesada nueva que se quiera despachar vía `queue_service`
  queda obligada a declarar su costo estimado — decisiones de
  dimensionamiento de infraestructura dejan de ser tanteo.
- Verificado en vivo:
  - `tests/scale/test_queue_broker_detection.py` (6/6): el ping real a
    Redis, no la construcción lazy de Celery, es lo que decide el modo.
  - `tests/scale/test_resource_guard.py` (11/11): el circuit breaker
    rechaza tareas bajo carga simulada y las admite con margen; degrada
    sin `psutil`.
  - `tests/scale/test_map_reduce.py` (6/6) — criterio de éxito de la fase,
    de punta a punta: dos workers en DOS HILOS de sistema operativo
    distintos (`hilos_usados`), el event loop principal sigue latiendo
    cada ~30ms durante todo el Map (no bloquea), los dos workers corren en
    paralelo real (~0.3s totales, no ~0.6s secuencial), un worker que falla
    no tumba al otro, y el Líder recibe el resultado consolidado (Reduce).
