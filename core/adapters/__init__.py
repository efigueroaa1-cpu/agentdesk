"""
core/adapters — Adaptadores de protocolos externos (anillo externo, ADR-0004).

Cada adaptador traduce un protocolo (MQTT, Modbus, OPC-UA, …) al contrato
`MetricEvent`/`TelemetryPort` de core/ports. Se cablean en main.py
(composition root), nunca desde core/api.py ni desde los servicios.
"""
from core.adapters.mqtt_adapter import MqttTelemetryAdapter, SimuladorPlanta  # noqa: F401
