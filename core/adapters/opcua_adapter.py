"""
core/adapters/opcua_adapter.py — Adaptador industrial OPC-UA (ADR-0004).

MISMO contrato que MqttTelemetryAdapter: el cambio de protocolo es
transparente para agentes, servicios y UI.
  - Modo real:     AGENTDESK_OPCUA_ENDPOINT=opc.tcp://host:puerto/ruta +
                   asyncua instalado (lee los nodeIds del catálogo via
                   asyncua.sync — conexión lazy y persistente).
  - Modo simulado: SimuladorPlanta determinista (sin servidor OPC-UA).

El nodeId viaja en la metadata del MetricEvent (ADR-0001).

Mapeo de nodeIds definitivo de la fase de planta virtual (2026-07-25,
cierra el esqueleto ADR-0004): Prosys OPC UA Simulation Server expone en
ns=3 (Simulation) señales vivas de amplitud ±2.0. Cada sensor transforma
esa señal cruda a su rango físico: fisico = base + (crudo / 2.0) * amplitud
— los mismos base/amplitud que ya gobiernan el SimuladorPlanta, así el
Gemelo Digital ve rangos idénticos en ambos modos y los umbrales
warn/critico se ejercitan de forma realista.
"""
from __future__ import annotations

import logging
import os

from core.adapters.base import BaseTelemetryAdapter

logger = logging.getLogger(__name__)

# Amplitud de las señales de simulación de Prosys (Sinusoid/Sawtooth/...):
# oscilan en ±2.0 por defecto — el divisor de la transformación a físico.
AMPLITUD_CRUDA_PROSYS = 2.0

SENSORES: list[dict] = [
    # min_fisico/max_fisico: rango de validez FISICA ([INDUSTRIAL-INTEGRITY],
    # ADR-0021) — fuera de el, la lectura se descarta del Gemelo Digital.
    {
        "id": "nivel_estanque_1", "nombre": "Nivel Estanque 1",
        "node_id": "ns=3;i=1004", "unidad": "%",          # Sinusoid
        "base": 62.0, "amplitud": 22.0,                    # fisico: 40..84 %
        "umbral_warn": 79.0, "umbral_critico": 83.0,
        "min_fisico": 0.0, "max_fisico": 100.0,
    },
    {
        "id": "rpm_turbina_1", "nombre": "RPM Turbina 1",
        "node_id": "ns=3;i=1003", "unidad": "rpm",         # Sawtooth
        "base": 3400.0, "amplitud": 260.0,                 # fisico: 3140..3660
        "umbral_warn": 3600.0, "umbral_critico": 3650.0,
        "min_fisico": 0.0, "max_fisico": 5000.0,
    },
]


class OpcUaTelemetryAdapter(BaseTelemetryAdapter):
    """TelemetryPort sobre OPC-UA; sin endpoint configurado usa SimuladorPlanta."""

    SENSORES = SENSORES

    def __init__(self, endpoint: str | None = None, intervalo_s: float = 5.0, **kw):
        super().__init__(intervalo_s=intervalo_s, **kw)
        self._endpoint = endpoint if endpoint is not None else os.environ.get("AGENTDESK_OPCUA_ENDPOINT", "")
        self._cliente  = None   # asyncua.sync.Client (lazy, persistente)

    def protocolo(self) -> str:
        return "opcua" if self._endpoint else "simulador"

    def _leer_valor(self, sensor: dict) -> float:
        if not self._endpoint:
            return self._simulador.leer(sensor)
        return self._leer_nodo(sensor)

    def _conectar(self):
        """Cliente sync lazy y persistente; ConnectionError si el servidor
        no acepta la sesión — NUNCA se degrada en silencio al simulador
        con un endpoint configurado (integridad industrial, ADR-0021)."""
        if self._cliente is not None:
            return self._cliente
        try:
            from asyncua.sync import Client
        except ImportError as exc:
            raise ConnectionError(
                "asyncua no instalado — requerido con AGENTDESK_OPCUA_ENDPOINT "
                "configurado (pip install asyncua)."
            ) from exc
        cliente = Client(self._endpoint)
        try:
            cliente.connect()
        except Exception as exc:
            raise ConnectionError(
                f"OPCUA: no se pudo conectar a {self._endpoint}: {exc}"
            ) from exc
        logger.info("OPCUA: conexion establecida con %s", self._endpoint)
        self._cliente = cliente
        return cliente

    def _leer_nodo(self, sensor: dict) -> float:
        """Lee el nodeId real y transforma la señal cruda al rango físico."""
        cliente = self._conectar()
        try:
            crudo = float(cliente.get_node(sensor["node_id"]).read_value())
        except Exception as exc:
            raise ConnectionError(
                f"OPCUA: fallo leyendo {sensor['node_id']} "
                f"({sensor['id']}): {exc}"
            ) from exc
        fisico = sensor["base"] + (crudo / AMPLITUD_CRUDA_PROSYS) * sensor["amplitud"]
        return round(fisico, 2)

    def _cerrar_cliente(self) -> None:
        if self._cliente is None:
            return
        try:
            self._cliente.disconnect()
        except Exception:
            pass
        self._cliente = None

    async def _reconectar(self) -> None:
        """Cierra el cliente OPC-UA roto para forzar una conexión nueva (ADR-0012)."""
        self._cerrar_cliente()

    def detener(self) -> None:
        super().detener()
        self._cerrar_cliente()
