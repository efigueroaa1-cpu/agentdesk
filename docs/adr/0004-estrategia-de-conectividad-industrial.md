# ADR-0004 — Estrategia de Conectividad Industrial (Visión OT)

- **Estado:** Aceptado
- **Fecha:** 2026-07-14
- **Relacionado:** ADR-0001 (Puerto de Telemetría), ADR-0003 (Motor puro)

## Contexto

AgentDesk entra en la Fase 5 (Tools Industriales): recibir señales de planta
(sensores, PLCs, brokers de mensajería) y que los agentes reaccionen a ellas.
Los protocolos OT (MQTT, Modbus TCP, OPC-UA) tienen semánticas y librerías
muy distintas entre sí, y ninguna debe filtrarse hacia el núcleo: el
orquestador, los servicios y el frontend no pueden depender de un protocolo.

## Decisión

**Todo protocolo de planta entra como adaptador del `TelemetryPort`
(ADR-0001), nunca como integración directa.**

```
   Planta física / broker            AgentDesk
┌──────────────────────┐   ┌──────────────────────────────────────┐
│ sensores → MQTT ─────┼──→│ core/adapters/mqtt_adapter.py        │
│ PLC → Modbus TCP ────┼──→│ (futuro) modbus_adapter.py           │──→ MetricEvent
│ SCADA → OPC-UA ──────┼──→│ (futuro) opcua_adapter.py            │        │
└──────────────────────┘   └──────────────────────────────────────┘        ▼
                                              suscriptores (inyectados en main.py):
                                              1. Puente WS → ConnectionManager → UI
                                              2. ReactorIndustrial → reglas → tarea de agente
```

1. **Normalización única:** cada adaptador traduce su protocolo a
   `MetricEvent` (`core/ports/telemetry_port.py`); lo específico (topic MQTT,
   registro Modbus, nodeId OPC-UA) viaja en `metadata` sin contaminar el
   contrato.
2. **Composición en `main.py`, jamás en `core/api.py`:** el adaptador se
   instala registrando un handler de startup sobre la app
   (`instalar_en_app(app, broadcast=manager.broadcast)`) activado por la
   variable `AGENTDESK_INDUSTRIAL` (`sim` = simulador de planta, `mqtt` =
   broker real vía `AGENTDESK_MQTT_BROKER`). api.py y el frontend no cambian:
   la UI ya consume el WS `/ws/telemetria` a través de su propio puerto
   (`useMonitorData.js`), así que los eventos industriales aparecen en la
   pestaña Consola del Módulo 8 sin tocar una línea de React.
3. **Reactividad declarativa:** el `ReactorIndustrial` del adaptador acepta
   reglas `(condición sobre MetricEvent) → acción async`. La acción típica es
   `orchestrator_service.ejecutar_tarea(agente_id, tarea)`: un cambio en una
   variable de planta dispara una tarea de agente sin polling del frontend.
4. **Modo simulado de primera clase:** `SimuladorPlanta` genera señales
   deterministas (seed fija) con excursiones que cruzan umbrales — el mismo
   principio del MockProvider: demo y tests sin planta, sin broker y sin red.
5. **Catálogo OT sobre base común (Fase 6):** la maquinaria compartida
   (estado de fuentes, difusión, reactor, ciclo) vive en
   `core/adapters/base.py`; cada protocolo solo define su catálogo de
   sensores y `_leer_valor()`. Adaptadores: `mqtt_adapter` (operativo),
   `modbus_adapter` y `opcua_adapter` (esqueletos con el mismo contrato,
   modo real activable por `AGENTDESK_MODBUS_HOST` / `AGENTDESK_OPCUA_ENDPOINT`).
6. **Cola Resiliente (Queue Mode):** en redes de planta inestables el WS
   puede caerse momentáneamente. Cada suscriptor tiene una cola pendiente
   acotada (500 eventos): la entrega se reintenta con backoff y, si el
   suscriptor no responde, el evento se conserva y se re-entrega EN ORDEN
   al reconectar. La cola es por-suscriptor: un consumidor caído no frena
   al resto. Al llenarse se descarta lo más viejo dejando log (backpressure
   explícito, nunca memoria infinita).

## Consecuencias

- Añadir Modbus/OPC-UA = escribir un adaptador que implemente `TelemetryPort`
  y cablearlo en main.py; núcleo, servicios, api.py y UI intactos.
- Las reglas del Guardián se amplían: `core/services|domain|ports|repositories`
  no pueden importar `core.adapters` (los adaptadores son anillo externo).
- El broker/protocolo es reemplazable por config, y el simulador garantiza
  que la Fase 5 sea testeable en el gate desde el día uno.
