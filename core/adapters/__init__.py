"""
core/adapters — Adaptadores de protocolos externos (anillo externo, ADR-0004).

Cada adaptador traduce un protocolo (MQTT, Modbus, OPC-UA, …) al contrato
`MetricEvent`/`TelemetryPort` de core/ports. Se cablean en main.py
(composition root), nunca desde core/api.py ni desde los servicios.
"""
from core.adapters.base import BaseTelemetryAdapter, ReactorIndustrial, SimuladorPlanta  # noqa: F401
from core.adapters.mqtt_adapter import MqttTelemetryAdapter      # noqa: F401
from core.adapters.modbus_adapter import ModbusTelemetryAdapter  # noqa: F401
from core.adapters.opcua_adapter import OpcUaTelemetryAdapter    # noqa: F401
