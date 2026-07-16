# ADR-0015 — Optimización de Frontend, CI/CD y Modularización del Núcleo

- **Estado:** Aceptado
- **Fecha:** 2026-07-16
- **Relacionado:** ADR-0002 (reglas de imports hexagonal), ADR-0003 (desacoplamiento
  del motor de agentes), ADR-0007/ADR-0014 (auditoría IA), ADR-0009 (HATs),
  ADR-0011 (delegación multi-agente Speak/Listen)

## Nota de verdad técnica antes de la decisión

El pedido de esta fase describía tres piezas de trabajo como si fueran
greenfield: (1) introducir code-splitting con `React.lazy()`/`Suspense` en
`MonitorPanel`, `SecurityPanel` y `ProyectosModule` para bajar el bundle
inicial de 1.11 MB a <500 KB; (2) extraer la lógica de `core/api.py` hacia
routers independientes, citando `auth_router.py` como ejemplo; (3) automatizar
el Quality Gate en CI/CD. Verificando el código real antes de escribir nada:

- **(1) es FALSO — ya estaba hecho.** `agentdesk-dashboard/src/App.jsx` ya
  importa los tres componentes citados (y otros 20 más) vía `lazy(() =>
  import(...))`, con `<Suspense>` envolviendo las rutas. `vite.config.js` ya
  trae `manualChunks` separando `vendor-maps` (react-simple-maps/d3-geo/
  topojson) y `vendor-charts` (recharts/d3-*) del resto — con un comentario
  explícito fechado de una "Fase 8" anterior no documentada en ADR. Se
  reconstruyó el build real (`npm run build`) para medir, no asumir: el
  bundle que carga `index.html` de forma eager es `index-*.js` (47.42 kB) +
  `vendor-*.js` (381.01 kB) = **428.43 KB sin comprimir (144.04 KB gzip)** —
  ya bajo el umbral de 500 KB pedido, sin tocar una línea. `vendor-charts`
  (372.79 KB) y `vendor-maps` (64.80 KB) NO se precargan — solo se piden
  cuando el navegador monta un componente lazy que los necesita.
- **(2) estaba parcialmente hecho.** `core/api_auth.py` (280 líneas) ya
  existía como precedente exacto de "endpoint HTTP + lógica en servicios,
  extraído de `core/api.py` con `APIRouter`" — literalmente el patrón que el
  pedido describe como `auth_router.py`. Lo que faltaba era extender ese
  mismo patrón al resto del archivo (1552 líneas) y moverlo dentro de un
  paquete `core/api/` real, que es donde el pedido lo situaba.
- **(3) sí era trabajo nuevo real** — no existía ningún workflow en
  `.github/workflows/`.

No se reescribió el frontend (ya cumplía el criterio de éxito) ni se
reinventó el patrón de router (ya existía uno probado). El trabajo real de
esta fase fue: documentar (1) con números medidos, generalizar (2) a todo
`core/api.py`, y construir (3) desde cero. Se agrega además el cierre de
brecha de testing (memoria HAT + delegación + auditoría simultáneas) pedido
explícitamente.

## Decisión

### 1. Frontend: mantener el code-splitting existente, documentarlo

No se modificó `App.jsx` ni `vite.config.js` — ambos ya satisfacen el
criterio de éxito. Se deja registro aquí para que quede trazable (no existía
un ADR previo que documentara esta optimización, algo que esta fase corrige).

Números reales del build (`npm run build`, medidos el 2026-07-16):

| Chunk | Tamaño sin comprimir | gzip | ¿Eager o lazy? |
|---|---:|---:|---|
| `index-*.js` (app shell) | 47.42 KB | 14.69 KB | Eager (siempre se carga) |
| `vendor-*.js` (React + resto) | 381.01 KB | 129.35 KB | Eager (`modulepreload`) |
| **Total bundle inicial** | **428.43 KB** | **144.04 KB** | — |
| `vendor-charts-*.js` | 372.79 KB | 97.02 KB | Lazy (solo si se monta un panel con gráficos) |
| `vendor-maps-*.js` | 64.80 KB | 23.12 KB | Lazy (solo si se monta `RegionalMap`) |
| `MonitorPanel-*.js` | 27.81 KB | 7.67 KB | Lazy |
| `SecurityPanel-*.js` | 22.63 KB | 5.98 KB | Lazy |
| `ProyectosModule-*.js` | 17.30 KB | 5.73 KB | Lazy |

`MainLayout.jsx` (shell: Sidebar + Header + slot de contenido) se deja
deliberadamente **fuera** de `React.lazy()` — es el layout que envuelve toda
la aplicación autenticada; volverlo lazy no reduciría el bundle inicial (se
seguiría necesitando en el primer render) y solo añadiría una cascada de
Suspense innecesaria.

### 2. Modularización de `core/api.py` → paquete `core/api/`

Se generaliza el patrón ya probado por `core/api_auth.py` (ahora
`core/api/auth_router.py`, contenido sin cambios) a todo el archivo:

| Archivo nuevo | Responsabilidad | Líneas |
|---|---|---:|
| `core/api/__init__.py` | Raíz de composición: instancia FastAPI, CORS, middleware no-cache de `/ui/`, registro de routers, eventos startup/shutdown, WS `/ws/telemetria` | 202 |
| `core/api/_state.py` | Estado compartido y mutable (ConnectionManager, `_bridge`/`_orquestador`, servicios singleton) — sin rutas HTTP | 281 |
| `core/api/schemas.py` | Los 14 modelos Pydantic de request, antes dispersos por todo el archivo | 102 |
| `core/api/auth_router.py` | `/auth/*` (movido de `core/api_auth.py`, sin cambios) | 286 |
| `core/api/agentes_router.py` | CRUD de agentes, ejecución, chat (normal+streaming), memoria, historial, uploads, proveedores | 304 |
| `core/api/sistema_router.py` | Salud, versión, backup, diagnóstico, `/metrics`, kill switch | 235 |
| `core/api/monitor_router.py` | Monitor web/planta, scheduler, dashboard, alertas, Curva-S, compliance, riesgo | 290 |
| `core/api/reportes_router.py` | Reportes PDF, Gantt, Finanzas, webhook WhatsApp | 291 |

`core/api/__init__.py` (la pieza que reemplaza al `core/api.py` original de
1552 líneas) queda en **202 líneas — una reducción del 87%**, muy por
encima del 40% pedido como criterio de éxito. Cada archivo nuevo nace bajo
el límite de 500 líneas del Guardián (`MAX_LINEAS`), sin necesitar entrada
en `LEGACY_OVERSIZE`.

**Por qué `_state.py` es un archivo aparte y no vive en `__init__.py`:**
`__init__.py` necesita importar los routers para registrarlos
(`app.include_router(...)`), y los routers necesitan leer el estado
compartido (`manager`, `_agent_service`, `_orquestador`...). Si ese estado
viviera en `__init__.py`, cada router tendría que importar el paquete que lo
está importando a él — circular. `_state.py` es una hoja del grafo de
imports (no importa nada de `__init__.py` ni de los routers), y los routers
leen su estado **siempre por atributo de módulo**
(`_state.manager`, `_state._orquestador`), nunca con
`from core.api._state import _orquestador` — porque `_bridge`/`_orquestador`
se reasignan en caliente (`registrar_bridge`/`registrar_orquestador`) y un
`from...import` habría congelado el valor `None` inicial en el namespace de
cada router.

**Contrato de import preservado.** `from core.api import app`,
`from core.api import manager`, `from core.api import registrar_bridge,
registrar_orquestador` siguen funcionando idéntico — `main.py`,
`test_security.py` y varios tests dependen exactamente de esas tres formas
de import, verificadas explícitamente antes de dar la fase por cerrada.

**Regla `CAPA_API` del Guardián.** `scripts/gate.py` bloqueaba imports de
`core.api`/`core.api_auth` desde domain/ports/services/repositories/adapters
(ADR-0002). El regex `core\.api\b` sigue cubriendo automáticamente todo el
paquete nuevo (`core.api._state`, `core.api.schemas`,
`core.api.agentes_router`, ...) sin cambios de lógica — se simplificó el
patrón (ya no hace falta el alternativo `api_auth`, absorbido dentro del
paquete) y se actualizó `check_pesado_sincrono()` para recorrer todo
`core/api/*.py` en vez de un único archivo hardcodeado.

### 3. CI/CD: `.github/workflows/ci.yml`

Corre en `windows-latest` (mismo intérprete que `gate.ps1`, evita tener que
portar el script a PowerShell Core multiplataforma) en cada `push` y
`pull_request`: instala dependencias Python + Node, corre `gate.ps1`
completo (que a su vez invoca `scripts/gate.py`, `test_security.py` y los
demás checks) y la suite completa de tests
(`python -m unittest discover`). Elimina la dependencia de que cada
desarrollador recuerde correr el gate localmente antes de subir.

### 4. Cierre de brecha de testing: interacción de tres subsistemas

`tests/integration/test_cross_systems.py` valida que memoria HAT
(`ContextHarness`, ADR-0009/0010), delegación multi-agente
(`DelegationService`, ADR-0011) y auditoría forense (`audit_service`,
ADR-0007) funcionan correctamente **al mismo tiempo**, no solo aisladas —
el hueco identificado en el análisis crítico previo del proyecto (ningún
test anterior combinaba más de un subsistema de la Fase 11+ a la vez).

**Hallazgo real durante la construcción del test (documentado, no
corregido — fuera de alcance de esta fase):** `DelegationService._auditar()`
(ADR-0011, Fase 13) no recibe ni pasa `contexto_hats` a
`audit_service.registrar_interaccion()`, a diferencia de
`OrchestratorService._auditar()` (ADR-0014, Fase 16), que sí lo hace para
`chat`/`ejecutar_tarea` directos. El HAT de memoria **sí opera
correctamente** dentro de una delegación (verificado interceptando
`core.providers.generate` y confirmando que el hecho recuperado llega al
prompt real que ve el LLM), pero ese contexto recuperado no queda
capturado en la columna `contexto_hats` de `auditoria_ia` cuando la
interacción llega vía delegación en lugar de chat/tarea directos. El test
`test_04_contexto_hats_no_se_propaga_hoy_a_la_traza_de_delegacion` deja
esto trazable con un assert que documenta el estado actual — si alguien
cierra la brecha en una fase futura, ese test empezará a fallar y señalará
exactamente dónde actualizar este ADR.

## Consecuencias

- El "archivo Dios" `core/api.py` deja de existir como tal; en su lugar hay
  un paquete con 8 archivos, cada uno con una responsabilidad legible y
  bajo el límite de tamaño del Guardián.
- Todo router nuevo que se agregue en el futuro sigue el mismo patrón
  (`APIRouter()` + import de `core.api._state` + `include_router()` en
  `__init__.py`) sin necesidad de reabrir esta discusión arquitectónica.
- El CI corre en Windows por pragmatismo (el gate ya está escrito y probado
  ahí); si el proyecto migra a Linux en producción, `gate.ps1` seguiría
  necesitando PowerShell Core cross-platform — deuda explícitamente fuera de
  alcance de esta fase.
- El bundle del frontend no cambió de tamaño porque ya cumplía el objetivo;
  el ADR deja el número medido como línea base para detectar regresiones
  futuras (p.ej. si una librería nueva se agrega sin lazy-load y el chunk
  eager crece de vuelta hacia 1 MB).
