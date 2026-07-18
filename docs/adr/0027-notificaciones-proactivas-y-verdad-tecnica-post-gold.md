# ADR-0027 — Notificaciones proactivas de alertas SLO y verdad técnica del pedido post-Gold

Fecha: 2026-07-18 · Estado: Aceptado · Fase: 29

## Contexto

Tras el lanzamiento v1.0.0 Gold llegó un pedido de "Excelencia Industrial"
con cuatro puntos. La auditoría de verdad técnica (obligatoria desde F12)
determinó que tres ya estaban resueltos por fases anteriores — este ADR lo
deja registrado para que nadie los "re-implemente" por error — y uno era
genuinamente nuevo.

### Verdad técnica de los cuatro puntos pedidos

1. **Blindaje de dependencias (lockfile exacto)** — YA EXISTE (F28,
   ADR-0026): `requirements.in` → pip-compile → `requirements.txt` con ~90
   pins `==` y trazabilidad `via`, verificado instalando un venv desde cero.
   No se toca.
2. **Strangler Fig sobre api.py (~1500 líneas)** — YA EJECUTADO (F17,
   ADR-0015): `core/api.py` no existe desde entonces; hoy es el paquete
   `core/api/` con un router por dominio. El archivo más grande
   (monitor_router.py) tiene 360 líneas — todos bajo el límite de 500 que
   el Guardián impone a cualquier archivo nuevo. No hay nada que dividir.
3. **Persistencia Hermes (ChromaDB + memory_port)** — YA EXISTE (F25,
   ADR-0023) con una decisión deliberada distinta: vector store embebido
   sobre SQLite stdlib en vez de ChromaDB (cero dependencias nuevas en el
   instalador, mismo recall verificado por tests). El scope
   `user_id+proyecto_id` es fail-closed y el Guardián lo vigila
   ([SEMANTIC-PRIVACY]). Reabrir la decisión ChromaDB requeriría superseder
   el ADR-0023 con una necesidad real (p. ej. ANN a millones de vectores);
   hoy no existe.
4. **Observabilidad activa (alertas proactivas)** — PARCIAL, y aquí está lo
   nuevo: `alert_service` (F20, ADR-0018) ya DETECTA los tres SLOs (fallos
   consecutivos de guardrails del PipelineProcessor —incluido
   LogicIntegrityFilter—, latencia p95, circuit breakers abiertos), pero el
   evento moría en el log. Si nadie mira el dashboard, nadie se entera.

El número de ADR pedido ("ADR-0015") estaba ocupado desde julio 2026 por la
optimización de frontend; esta decisión se numera 0027 (discrepancia de
pedido clase F12/14/22/26, documentada y resuelta).

## Decisión

Cerrar el bucle de observabilidad con un canal de salida hexagonal:

- **Puerto** `core/ports/notification_port.py`: `NotificationPort`
  (Protocol runtime-checkable) con `enviar(titulo, mensaje, severidad,
  metadatos) -> bool`, contrato best-effort (jamás propaga excepciones).
- **Adaptadores** `core/adapters/notification_adapter.py`:
  - `SlackWebhookAdapter` (Incoming Webhook, `AGENTDESK_SLACK_WEBHOOK`).
  - `WhatsAppCloudAdapter` (Cloud API de Meta: `AGENTDESK_WHATSAPP_TOKEN`
    + `_PHONE_ID` + `_DESTINO`).
  - Credenciales SOLO por entorno; transporte urllib stdlib con esquema
    https validado (mismo patrón nosec B310 de web_monitor/updater); sin
    dependencias nuevas en el instalador.
- **Despachador** `core/services/notification_service.py`: registro de
  canales por inyección (la composición vive en `core/api/__init__.py`,
  ADR-0004), cooldown de 10 min por tipo de alerta (el monitor corre cada
  60 s — sin cooldown una degradación sostenida bombardearía al operador),
  contadores de estado y span OTel `notificacion.despachar`. El cooldown se
  consume por INTENTO, no por éxito: un webhook roto no se martillea.
- **Cableado**: `alert_service.iniciar_monitor()` despacha cada evento
  detectado por `notification_service.notificar()`. Sin canales
  configurados la señal sigue quedando en el log crítico — cero pérdida.

### Regla nueva del Guardián — [ALERT-DISPATCH]

1. El puerto y el despachador existen y `alert_service` enruta por ellos.
2. Ningún servicio NUEVO importa transporte HTTP (`urllib.request`,
   `requests`, `httpx`, `aiohttp`, `http.client`) — los webhooks viven en
   adaptadores. `insights_service` (httpx a Ollama local, previo a la
   regla) queda grandfathered; `urllib.parse` no cuenta (parsear no es
   conectar).
3. Suite espejo `tests/observability/test_notificaciones.py` en verde; la
   del adaptador la exige [OT-TEST] automáticamente.

Trinquete del Guardián: 1171 → 1220 líneas (justificado en LEGACY_OVERSIZE).

## Consecuencias

- (+) Una racha de fallos del LogicIntegrityFilter (o cualquier guardrail)
  llega al bolsillo del operador en ≤60 s, sin dashboard abierto.
- (+) Cero dependencias nuevas: el instalador no crece.
- (+) Añadir un canal (correo, Teams, SMS) = un adaptador + una línea de
  composición; el despachador y la regla del gate no cambian.
- (−) El cooldown por tipo puede agrupar causas distintas del mismo tipo
  (dos proveedores con circuito abierto en <10 min → un solo aviso del
  segundo). Aceptado: el detalle completo siempre está en el log forense.
- (−) WhatsApp Cloud API exige infraestructura Meta Business del lado del
  usuario; por eso ambos canales son opcionales y el arranque no depende
  de ellos.
