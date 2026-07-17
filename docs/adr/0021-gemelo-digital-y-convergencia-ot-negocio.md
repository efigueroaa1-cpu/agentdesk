# ADR-0021 — Gemelo Digital Operativo: Convergencia OT ↔ Negocio

- **Estado:** Aceptado
- **Fecha:** 2026-07-17
- **Relacionado:** ADR-0001/0004/0012 (puerto de telemetría y adaptadores
  Modbus/OPC-UA/MQTT — la señal física), ADR-0013 ([DB-CONCURRENCY], la
  regla que moldea dónde vive el historial OT), ADR-0018 (alert_service,
  el precedente de alertas activas), ADR-0019/0021 (Map-Reduce, la capa
  de evaluación paralela), Sprint 8 histórico (Curva S / EVM)

## Nota de verdad técnica antes de la decisión

1. **El "servicio de Curva S" pedido ya existía completo.** El pedido dice
   "implementa en core/analytics.py un servicio que correlacione la
   telemetría con la Curva S" — `core/analytics.py` YA ES el motor EVM
   completo (PV/EV/AC, SPI/CPI, EAC/VAC, alertas ALTO/CRITICO, Sprint 8),
   integrado con Gantt (`core/gantt.py`, CPM real) y Finanzas
   (`analisis_financiero`). Lo genuinamente nuevo es la correlación con la
   señal FÍSICA — eso se implementó como `MotorCorrelacionOT` en el mismo
   módulo, sin tocar el motor clásico.
2. **La telemetría industrial era efímera.** Cada `MetricEvent` se difundía
   por WebSocket (Cola Resiliente, ADR-0012) y se descartaba — "las últimas
   1000 métricas" no existían en NINGUNA parte del sistema. Y no es un
   descuido arreglable con un INSERT: la regla `[DB-CONCURRENCY]`
   (ADR-0013) prohíbe deliberadamente a los adaptadores escribir en la DB
   (un INSERT por tick de sensor es exactamente la contención que esa regla
   evita). Se creó `core/telemetry_history.py`: ring buffer en memoria
   (deque 2000, thread-safe), mismo patrón que los spans de
   `telemetry_otel`. Volatilidad aceptada y documentada: la ventana
   reciente alimenta el Gemelo; la trazabilidad de largo plazo sigue
   siendo de la auditoría.
3. **Los sensores no tenían rango de validez física.** Los 7 sensores de
   los 3 catálogos (Modbus/OPC-UA/MQTT) declaraban `umbral_warn`/
   `umbral_critico` (alarmas de proceso) pero ningún min/max físico: una
   lectura de -500 m³/h o 99999 °C entraba al sistema como dato legítimo
   ("muy crítico", pero legítimo). Con un Gemelo Digital que proyecta
   fechas y presupuestos desde esos datos, eso es data poisoning directo
   a decisiones de negocio.

## Decisión

### 1. Vinculación PLC ↔ Gantt ↔ Finanzas (`MotorCorrelacionOT`)

`motor_correlacion.vincular(proyecto_id, sensor_id, rendimiento_nominal)`
asocia tags de planta a un proyecto Gantt con su régimen nominal (valor del
tag a producción plena). `factor_produccion()` calcula el rendimiento real:
media de la ventana reciente del historial OT / nominal, acotado a
[0, 1.25] — 1.0 = a plan, <0.05 = parada de máquina detectada. Sin vínculos
o sin telemetría, factor 1.0 explícito: el Gemelo no inventa datos que no
tiene, la Curva S clásica sigue valiendo tal cual.

### 2. Proyección ajustada y detección de impacto en cronograma

`proyeccion_ajustada(proyecto_id)`: el trabajo restante planificado
(fin_plan − hoy, del CPM real de Gantt) se escala por 1/factor →
`fin_proyectado`, `impacto_cronograma` y `dias_atraso_proyectados`. En
paralelo, el EAC financiero se ajusta: `EAC_ajustado = BAC / (CPI · factor)`
→ `riesgo_presupuesto` si supera BAC+5%. La emisión de
`AUDITORIA_SEGURIDAD` ante riesgo financiero vive AQUÍ, en código
determinista — una alerta de seguridad no puede depender del juicio de un
LLM. Esto adelanta a HOY la detección de un atraso que el cronograma (que
solo ve `pct_completado` cargado a mano) confesaría semanas después.

### 3. Analista de Riesgos en paralelo (Map-Reduce sobre 1000 métricas)

`core/services/risk_analysis_service.py`, dos capas deliberadas:
**determinista** (screening estadístico de las últimas 1000 métricas:
parada de máquina, régimen crítico sostenido; cruzado con la proyección →
`AUDITORIA_SEGURIDAD` SIEMPRE que corresponda) y **cognitiva** (el dataset
se parte en chunks con digest compacto y el agente Analista los evalúa EN
PARALELO vía Map-Reduce — requirió extender `MapReduceService.ejecutar()`
con `prompts` por worker, el patrón Map-Reduce clásico de particionar
datos; hasta ahora todos los workers recibían el mismo prompt). Si la capa
cognitiva falla (sin LLM, sin orquestador), la determinista sigue
alertando — nunca al revés.

### 4. Dashboard Ejecutivo y endpoints

- `GET /analytics/proyeccion-ot/{proyecto_id}` (supervisor+): la proyección
  ajustada; emite `riesgo_ot_alerta` por WebSocket (rol supervisor+) ante
  riesgo — la alerta "en el dashboard" del criterio de éxito.
- `GET /analytics/roi` (supervisor+): costo de ejecución acumulado (USD/
  tokens de IA vía `resumen_costos` + carga de recursos del host vía
  `resource_guard`) vs. valor del avance físico (EV de la Curva S × factor
  de producción real) → ROI.
- `POST /analytics/riesgo-ot/{proyecto_id}` (supervisor+, en la lista
  blanca del contrato de auth con justificación): dispara el análisis del
  Analista de Riesgos.

### 5. Guardián `[INDUSTRIAL-INTEGRITY]`

Los 7 sensores ganan `min_fisico`/`max_fisico` (rango de validez FÍSICA,
distinto de las alarmas de proceso). `base.py::_evento_de()` valida cada
lectura: fuera de rango → `AUDITORIA_SEGURIDAD` + nivel crítico + marca
`fuera_de_rango_fisico`; el evento SÍ se difunde al operador (debe ver que
algo anda mal) pero `telemetry_history` lo excluye — el Gemelo Digital
nunca razona sobre lecturas físicamente imposibles.
`check_industrial_integrity()` en gate.py valida por **AST** (los catálogos
son literales — `ast.literal_eval`, no regex frágil) que todo sensor de
todo catálogo declare rangos numéricos coherentes (min < max), y que la
validación de base.py siga aplicándolos.

## Consecuencias

- Una parada de máquina visible en un tag Modbus ajusta HOY la fecha fin
  proyectada y el EAC del proyecto — la conversación "la planta se atrasó"
  y la conversación "el presupuesto no alcanza" dejan de ocurrir con
  semanas de diferencia.
- Las alertas de riesgo financiero-industrial son deterministas y
  auditables; el LLM agrega diagnóstico narrativo en paralelo, no decide
  si alertar.
- El historial OT es volátil por diseño (ventana en memoria) — cualquier
  fase futura que necesite telemetría histórica persistente debe diseñar
  su propia agregación (downsampling a DB), no "agregar el INSERT" que
  [DB-CONCURRENCY] prohíbe.
- Data poisoning al Gemelo tiene ahora dos barreras: rango físico por
  sensor (aplicado en runtime, exigido por el gate) y exclusión del
  historial de correlación.
- Verificado en vivo (`tests/industrial/test_gemelo_digital.py`, 8/8): el
  criterio de éxito de punta a punta — parada de máquina Modbus simulada
  (caudal 0 en la MISMA forma de evento que producen los adaptadores) →
  `impacto_cronograma=True`, días de atraso proyectados, `spi_fisico` <
  SPI reportado, `riesgo_presupuesto=True` con `AUDITORIA_SEGURIDAD`
  emitida; lecturas imposibles marcadas/auditadas/excluidas; el Analista
  de Riesgos evaluando 200 métricas en chunks paralelos (hilos distintos,
  prompts distintos por segmento) y la recuperación de la máquina
  normalizando la proyección sola.
