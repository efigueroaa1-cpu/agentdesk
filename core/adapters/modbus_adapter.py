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
    # min_fisico/max_fisico: rango de validez FISICA ([INDUSTRIAL-INTEGRITY],
    # ADR-0021) — fuera de el, la lectura se descarta del Gemelo Digital.
    {
        "id": "temp_reactor_2", "nombre": "Temperatura Reactor 2",
        "registro": 40001, "unit": 1, "escala": 0.1, "unidad": "°C",
        "base": 180.0, "amplitud": 35.0,
        "umbral_warn": 205.0, "umbral_critico": 212.0,
        "min_fisico": 0.0, "max_fisico": 350.0,
    },
    {
        "id": "caudal_bomba_5", "nombre": "Caudal Bomba 5",
        "registro": 40003, "unit": 1, "escala": 0.01, "unidad": "m³/h",
        "base": 42.0, "amplitud": 12.0,
        "umbral_warn": 51.0, "umbral_critico": 53.5,
        "min_fisico": 0.0, "max_fisico": 120.0,
    },
]


# Tags ESCRIBIBLES ([INDUSTRIAL-ACTION], ADR-0024): min_escritura/max_escritura
# es el limite fisico de seguridad — ningun comando puede cruzarlo, lo valida
# el filtro determinista de base.py antes de tocar la red.
ACTUADORES: list[dict] = [
    {
        "id": "reset_alarma_e117", "nombre": "Reset Alarma E-117",
        "registro": 40100, "unit": 1, "escala": 1.0, "unidad": "",
        "min_escritura": 0.0, "max_escritura": 1.0,
    },
    {
        "id": "setpoint_temp_reactor_2", "nombre": "Setpoint Temperatura Reactor 2",
        "registro": 40010, "unit": 1, "escala": 0.1, "unidad": "°C",
        "min_escritura": 20.0, "max_escritura": 205.0,
    },
]


class ModbusTelemetryAdapter(BaseTelemetryAdapter):
    """TelemetryPort + ActuationPort sobre Modbus TCP; sin host usa SimuladorPlanta."""

    SENSORES = SENSORES
    ACTUADORES = ACTUADORES

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
            if self._cliente.connect():
                logger.info("MODBUS: conexion establecida con %s:%s",
                            host, puerto or 502)
            else:
                logger.warning("MODBUS: no se pudo conectar a %s:%s — "
                               "verificar que el esclavo este escuchando",
                               host, puerto or 502)

        # Dirección Modbus 4xxxx → offset 0-based del holding register
        offset    = sensor["registro"] - 40001
        respuesta = self._cliente.read_holding_registers(offset, count=1, slave=sensor["unit"])
        if respuesta.isError():
            raise ConnectionError(f"Modbus error leyendo {sensor['registro']}: {respuesta}")
        return round(respuesta.registers[0] * sensor["escala"], 2)

    def _escribir_valor(self, actuador: dict, valor: float) -> str:
        """
        Escritura real de un holding register (Modbus Write, ADR-0024).
        Sin host o sin pymodbus: registro simulado (default de base.py).
        El comando YA paso el filtro determinista de escribir_tag().
        """
        if not self._host:
            return super()._escribir_valor(actuador, valor)
        try:
            from pymodbus.client import ModbusTcpClient  # noqa: F401
        except ImportError:
            logger.warning("pymodbus no instalado — escritura '%s' en modo simulador.",
                           actuador["id"])
            return super()._escribir_valor(actuador, valor)

        if self._cliente is None:
            from pymodbus.client import ModbusTcpClient
            host, _, puerto = self._host.partition(":")
            self._cliente = ModbusTcpClient(host, port=int(puerto or 502))
            self._cliente.connect()

        offset = actuador["registro"] - 40001
        crudo  = int(round(valor / actuador["escala"]))
        respuesta = self._cliente.write_register(offset, crudo, slave=actuador["unit"])
        if respuesta.isError():
            raise ConnectionError(
                f"Modbus error escribiendo {actuador['registro']}: {respuesta}")
        return f"write_register({actuador['registro']}={crudo})"

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
