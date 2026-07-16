# ADR-0012 — Conectividad Industrial (OT) y Resiliencia de Mensajería

- **Estado:** Aceptado
- **Fecha:** 2026-07-15
- **Relacionado:** ADR-0001 (Puerto de Telemetría), ADR-0004 (Estrategia de
  Conectividad Industrial), ADR-0011 (sandbox y delegación)

## Nota de verdad técnica antes de la decisión

El pedido de esta fase describía crear `core/adapters/ot_adapters.py` con
adaptadores Modbus TCP / OPC-UA / MQTT nuevos, y un contrato `MetricEvent`
con campos `agente_id, nombre_metrica, valor, timestamp`. Verificando el
código real antes de escribir nada:

- Los tres adaptadores **ya existen** desde ADR-0004 (Fase 5/6):
  `core/adapters/modbus_adapter.py`, `mqtt_adapter.py`, `opcua_adapter.py`,
  todos implementando `TelemetryPort` sobre la maquinaria común de
  `core/adapters/base.py`, cada uno con su suite en `tests/industrial/`.
  Crear un `ot_adapters.py` paralelo habría duplicado protocolos ya
  resueltos y roto la regla de un único adaptador por protocolo (ADR-0004).
- El contrato real de `MetricEvent` (`core/ports/telemetry_port.py`) es
  `fuente, tipo, valor, unidad, ts, nivel, metadata` — no
  `agente_id/nombre_metrica/timestamp`. Cambiarlo habría roto los tres
  adaptadores, el puente WebSocket del dashboard y toda la suite
  `tests/industrial/` existente, sin ninguna ganancia funcional real.
- La "Cola Resiliente" del lado del **suscriptor** (WS/dashboard caído,
  reintentos + backoff corto, redelivery en orden) **ya existe** en
  `BaseTelemetryAdapter._difundir/_pendientes` desde la Fase 6, con su
  propio test (`test_05b_cola_resiliente_sin_perdida_ante_ws_caido`).

Lo que SÍ faltaba, verificado leyendo el código: si la lectura de la
**fuente** (PLC, broker) fallaba — timeout, conexión caída — `ciclo()` no
capturaba la excepción. Un solo fallo de lectura mataba la `asyncio.Task`
completa en silencio, deteniendo TODA la telemetría de ese adaptador hasta
un reinicio manual. Ese es el vacío real que cierra esta fase.

## Decisión

### 1. Reconexión automática con backoff exponencial (fuente)

`BaseTelemetryAdapter.ciclo()` envuelve cada tick en `try/except`: si
`_leer_valor()` falla, aplica backoff exponencial (2s → 4s → 8s → ... tope
60s), llama al hook `_reconectar()` de la subclase, y reintenta — **nunca**
deja morir la tarea. Un tick exitoso resetea el backoff a cero.

`_reconectar()` es no-op por defecto; `ModbusTelemetryAdapter` y
`OpcUaTelemetryAdapter` lo sobreescriben para cerrar y anular su cliente
roto, forzando una conexión nueva en el siguiente intento (no reintentan
sobre un socket ya muerto). `MqttTelemetryAdapter` recibe el mismo
tratamiento en su conexión inicial (`_ciclo_mqtt`): `cliente.connect()` es
síncrono y lanzaba de inmediato si el broker estaba caído, ANTES de que el
reconector automático de `paho-mqtt` (que solo actúa tras una primera
conexión exitosa) pudiera intervenir.

### 2. Guardián — contrato MetricEvent y credenciales OT

- `[METRIC-CONTRACT]`: todo `MetricEvent(...)` construido en
  `core/adapters/*.py` debe usar exclusivamente los campos reales del
  contrato (`fuente, tipo, valor, unidad, ts, nivel, metadata`).
- `[TOOL-SECURITY]` (extensión): ningún adaptador puede tener una
  credencial de conexión embebida en una URI (`usuario:clave@host`) como
  literal — deben usar `os.environ.get("AGENTDESK_*_HOST/BROKER/ENDPOINT")`
  (ya el patrón real de los tres adaptadores) o un futuro KeyVault, nunca
  código versionado.

## Consecuencias

- Cero cambios de contrato hacia el dashboard, el reactor industrial o el
  resto de `tests/industrial/` — los 24 tests existentes de esa carpeta
  siguen en verde sin modificación.
- La resiliencia queda completa en ambos extremos del pipeline de
  telemetría: fuente (nuevo, esta fase) y suscriptor (ya existente, Fase 6).
- `tests/industrial/test_ot_reconexion.py` simula una caída de red real de
  un PLC Modbus inyectando un doble de `pymodbus` en `sys.modules` (la
  librería no está instalada en este entorno — dependencia opcional,
  ADR-0005/0007) y demuestra: lectura de un registro simulado, reconexión
  tras fallos consecutivos con backoff 2s/4s/8s, `_reconectar()` forzando
  un cliente nuevo, y — combinando ambos lados — cero pérdida de datos
  incluso cuando la fuente Y el suscriptor fallan en la misma ventana.
