# ADR-0024 — Comando y Control Industrial de Bucle Cerrado

- Estado: Aceptado (2026-07-17, Fase 26)
- Relacionados: ADR-0001 (puerto de telemetria), ADR-0004 (estrategia OT),
  ADR-0018 (retencion), ADR-0021 (integridad fisica), ADR-0023 (Hermes)

## Contexto

Hasta la Fase 25 AgentDesk era SOLO-LECTURA hacia la planta: telemetria
entrante (Modbus/MQTT/OPC-UA), cero escritura. Habilitar actuadores es el
paso mas critico del proyecto — un comando erroneo mueve fierros.

Hallazgos de verdad tecnica:

1. El `ReactorIndustrial` (ADR-0004) ya dispara TAREAS DE AGENTE ante
   umbrales, pero jamas escribio a la planta — el "bucle" estaba abierto
   a proposito. Esta fase lo cierra CON el operador dentro, no sin el.
2. `TelemetryPort` es un Protocol runtime-checkable usado en tests de
   contrato: agregarle `write_tag` obligatorio rompia a los adaptadores
   solo-lectura. Se creo `ActuationPort` SEPARADO — leer es inocuo,
   escribir se declara pidiendo el puerto de actuacion explicitamente.
3. La regla de imports (ADR-0002) prohibe `core.adapters` en services:
   `ot_command_service` recibe los adaptadores por INYECCION desde la
   composicion (`core/api/__init__`), jamas los importa.
4. La deuda declarada de ADR-0023 (Hermes sin retencion) se salda aqui:
   la purga periodica de ADR-0018 ahora tambien cubre la memoria vectorial.

## Decision

### 1. Protocolo de seguridad de escritura (Human-in-the-loop OBLIGATORIO)

```
agente --proponer--> [filtro deterministico] --> bandeja PENDIENTE
                                                     |
    operador supervisor+ --aprobar/rechazar-- (TTL 15 min)
                                                     |
                              [filtro deterministico OTRA VEZ]
                                                     |
                        adaptador.escribir_tag --> planta
```

- **El agente solo PROPONE** (`proponer_comando_ot`, herramienta del
  orquestador). La propuesta pasa el filtro determinista YA en origen:
  una accion fuera de limites ni siquiera llega al operador.
- **Nada sale a la red sin `aprobar()`**: endpoint con RBAC supervisor+
  verificado dentro del handler. El rechazo tambien queda auditado.
- **Las propuestas expiran (15 min)**: aprobar sobre un diagnostico viejo
  es en si mismo peligroso; expirada => re-diagnosticar.
- **Doble validacion**: el filtro corre al proponer Y al ejecutar (la
  configuracion pudo cambiar entre ambos momentos).
- **Auditoria forense total**: `ot_propuesta` / `ot_comando` /
  `ot_rechazo` en `auditoria_ia`, con user_id del agente proponente y del
  operador que resolvio.

### 2. Filtro determinista (limites fisicos de escritura)

Cada adaptador declara su catalogo `ACTUADORES` con
`min_escritura`/`max_escritura` — el limite fisico de seguridad del tag.
`base.py::escribir_tag()` valida con aritmetica pura (tag existe, valor
numerico, dentro de limites) ANTES de tocar la red; el rechazo va a
`AUDITORIA_SEGURIDAD`. **Ningun LLM participa en esta decision** — el
juicio del modelo propone, la aritmetica y el humano disponen.

Implementaciones: Modbus `write_register` (con escala inversa), MQTT
`publish` (topic de comando, QoS 1). En modo simulador la escritura se
registra en `adaptador.escrituras` — evidencia verificable en tests y
demo sin hardware.

### 3. Habilidades de Accion (ADR-0023 extendido)

Una receta puede declarar `comandos_ot` (forma validada al extraer). El
prompt generado instruye usar `proponer_comando_ot` y declara SIEMPRE que
requiere aprobacion del operador — una habilidad jamas salta el
Human-in-the-loop, solo lo alimenta con contexto.

### 4. Purga Hermes (deuda saldada)

`purgar_registros_antiguos()` (ADR-0018) ahora invoca
`hermes().purgar_antiguos(dias)`: los recuerdos `tipo="interaccion"` mas
viejos que la retencion se ELIMINAN (no se anonimizan: el embedding es
una proyeccion del contenido — anonimizar el texto dejando el vector
conservaria la huella de la PII). Las recetas `tipo="habilidad"` no se
purgan: son artefactos curados de conocimiento operativo, no
conversaciones. Base ligera + GDPR con la MISMA politica
(`AGENTDESK_AUDITORIA_RETENCION_DIAS`) y el MISMO monitor diario.

### 5. Guardian [INDUSTRIAL-ACTION]

- Todo `ACTUADORES` declara limites numericos `min < max` (AST literal,
  mismo mecanismo que [INDUSTRIAL-INTEGRITY]).
- `escribir_tag()` debe aplicar `_validar_comando` — la escritura sin
  filtro queda estructuralmente prohibida.
- Todo endpoint `POST /ot/*` debe contener `tiene_permiso(..,"supervisor")`
  dentro del handler.
- La suite `tests/industrial/test_actuadores.py` corre en cada gate (via
  el discover industrial existente).

## Consecuencias

- (+) Criterio de exito verificado end-to-end en test: recuerdo Hermes de
  E-117 (3 dias) -> propuesta del agente via herramienta real -> cero
  escrituras antes de aprobar -> aprobacion -> UNA escritura Modbus
  simulada -> auditoria completa.
- (+) El dashboard gana la bandeja "Acciones OT" (Monitor): aprobar y
  rechazar con un clic, con broadcast WS de propuestas nuevas.
- (−) Las propuestas viven en memoria del proceso (se pierden al
  reiniciar): aceptable porque expiran en 15 min de todos modos y el
  rastro forense queda en DB. Persistirlas seria darle mas vida de la
  que el TTL permite.
- (−) El modo real Modbus/MQTT de escritura queda verificado contra
  simulador y fakes (sin PLC/broker en esta maquina) — misma limitacion
  honesta que las Fases 13/15/22; el smoke de staging es el lugar del
  PASS con fierros reales.
