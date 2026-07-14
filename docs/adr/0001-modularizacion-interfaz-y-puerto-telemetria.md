# ADR-0001 — Modularización de la interfaz y Puerto de Telemetría agnóstico

- **Estado:** Aceptado
- **Fecha:** 2026-07-13
- **Contexto de commits:** `801b23c` (AgentPerformancePanel), `2abfad8` (MonitorPanel)

## Contexto

El frontend acumuló "componentes Dios": `AgentPerformancePanel.jsx` (511 líneas) y
`MonitorPanel.jsx` (1727 líneas / 57 KB) mezclaban en un solo archivo la gestión de
estado, la conexión WebSocket, el polling REST y toda la presentación. Además,
AgentDesk apunta a una fase de conectividad industrial: las mismas vistas de
monitoreo deberán alimentarse en el futuro de telemetría OT (Modbus TCP, OPC-UA),
no solo de scraping/APIs web.

## Decisión

1. **Patrón de split obligatorio para paneles:** orquestador delgado (<40 líneas)
   + hook de lógica + componentes presentacionales puros (≤150 líneas, props y
   callbacks, sin estado global). Aplicado en `src/components/agents/performance/`
   y `src/components/monitor/`.

2. **Puerto de Telemetría en el frontend:** `src/hooks/useMonitorData.js` es la
   ÚNICA puerta de entrada de telemetría a la UI del Módulo 8. Expone el contrato
   agnóstico:

   ```js
   { fuentes, cargando, eventos, historial, alertas, acciones }
   // acciones: recargar, alternar, cambiarFrecuencia, ejecutarAhora,
   //           cargarHistorial, cargarAlertas, limpiarEventos
   ```

   Una **fuente** es cualquier unidad monitoreable (`id`, `nombre`, `activo`,
   `estado`, `intervalo_min`, `ultima_fetch`); un **evento** es un mensaje
   normalizado con `_ts` (ring buffer de 200). Nada en el contrato asume HTTP,
   WebSocket ni scraping.

3. **Espejo backend del puerto:** `core/ports/telemetry_port.py` define
   `MetricEvent` (evento normalizado con `metadata` para lo específico del
   protocolo) y el Protocol `TelemetryPort` (`fuentes`, `leer`, `suscribir`,
   `alternar`, `cambiar_frecuencia`). El adaptador actual es el monitor web
   (REST + WS `/ws/telemetria`).

## Consecuencias

- **Conectar Modbus/OPC-UA no toca la UI:** se escribe un adaptador backend que
  implemente `TelemetryPort` (p.ej. `ModbusAdapter` que mapee registros a
  `MetricEvent`) y sus fuentes aparecen en `useMonitorData` con el mismo contrato.
  Ni `MonitorPanel.jsx` ni sus 15 subcomponentes cambian.
- Los componentes presentacionales son testeables sin red (reciben datos por props).
- Restricción aceptada: el formulario de configuración (`MonitorConfigForm`) solo
  edita `activo` e `intervalo_min` porque `PUT /scheduler/tareas/{id}` no soporta
  más campos; ampliar el formulario exige primero ampliar ese endpoint.

## Alternativas descartadas

- **Un hook por pestaña:** fragmentaría la suscripción WS (una conexión por vista)
  y duplicaría el estado de fuentes.
- **Estado global (Redux/Zustand):** innecesario para un módulo; el puerto único
  ya centraliza el estado y añadir una librería contradice "Deuda Cero".
