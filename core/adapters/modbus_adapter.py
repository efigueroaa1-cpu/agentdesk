"""
core/adapters/modbus_adapter.py — Adaptador industrial Modbus TCP (ADR-0004).

Esqueleto con el MISMO contrato que MqttTelemetryAdapter: el cambio de
protocolo es transparente para agentes, servicios y UI.
  - Modo real:     AGENTDESK_MODBUS_HOST=host[:puerto] + pymodbus instalado
                   (lee holding registers y aplica `escala` por sensor).
  - Modo simulado: SimuladorPlanta determinista (sin PLC, sin red).

Los detalles del protocolo (registro, unit/slave, escala) viajan en la
metadata del MetricEvent — el contrato no se contamina (ADR-0001).
"""
from __future__ import annotations

import logging
import os

from core.adapters.base import BaseTelemetryAdapter

logger = logging.getLogger(__name__)

# Holding registers típicos de un PLC de línea (direcciones ilustrativas)
SENSORES: list[dict] = [
    {
        "id": "temp_reactor_2", "nombre": "Temperatura Reactor 2",
        "registro": 40001, "unit": 1, "escala": 0.1, "unidad": "°C",
        "base": 180.0, "amplitud": 35.0,
        "umbral_warn": 205.0, "umbral_critico": 212.0,
    },
    {
        "id": "caudal_bomba_5", "nombre": "Caudal Bomba 5",
        "registro": 40003, "unit": 1, "escala": 0.01, "unidad": "m³/h",
        "base": 42.0, "amplitud": 12.0,
        "umbral_warn": 51.0, "umbral_critico": 53.5,
    },
]


class ModbusTelemetryAdapter(BaseTelemetryAdapter):
    """TelemetryPort sobre Modbus TCP; sin host configurado usa SimuladorPlanta."""

    SENSORES = SENSORES

    def __init__(self, host: str | None = None, intervalo_s: float = 5.0, **kw):
        super().__init__(intervalo_s=intervalo_s, **kw)
        self._host    = host if host is not None else os.environ.get("AGENTDESK_MODBUS_HOST", "")
        self._cliente = None   # pymodbus AsyncModbusTcpClient (lazy)

    def protocolo(self) -> str:
        return "modbus" if self._host else "simulador"

    def _leer_valor(self, sensor: dict) -> float:
        if not self._host:
            return self._simulador.leer(sensor)
        return self._leer_registro(sensor)

    def _leer_registro(self, sensor: dict) -> float:
        """
        Lectura real de un holding register (fase de conexión a PLC).
        Requiere pymodbus; si falta, degrada al simulador con aviso.
        """
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError:
            logger.warning("pymodbus no instalado — sensor '%s' en modo simulador.", sensor["id"])
            return self._simulador.leer(sensor)

        if self._cliente is None:
            host, _, puerto = self._host.partition(":")
            self._cliente = ModbusTcpClient(host, port=int(puerto or 502))
            self._cliente.connect()

        # Dirección Modbus 4xxxx → offset 0-based del holding register
        offset    = sensor["registro"] - 40001
        respuesta = self._cliente.read_holding_registers(offset, count=1, slave=sensor["unit"])
        if respuesta.isError():
            raise ConnectionError(f"Modbus error leyendo {sensor['registro']}: {respuesta}")
        return round(respuesta.registers[0] * sensor["escala"], 2)

    async def _reconectar(self) -> None:
        """Cierra el cliente Modbus roto para forzar una conexión nueva (ADR-0012)."""
        if self._cliente is not None:
            try:
                self._cliente.close()
            except Exception:
                pass
            self._cliente = None

    def detener(self) -> None:
        super().detener()
        if self._cliente is not None:
            try:
                self._cliente.close()
            except Exception:
                pass
            self._cliente = None
