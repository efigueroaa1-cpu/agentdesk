"""
core/adapters/opcua_adapter.py — Adaptador industrial OPC-UA (ADR-0004).

Esqueleto con el MISMO contrato que MqttTelemetryAdapter: el cambio de
protocolo es transparente para agentes, servicios y UI.
  - Modo real:     AGENTDESK_OPCUA_ENDPOINT=opc.tcp://host:4840 + asyncua
                   instalado (lee los nodeIds del catálogo).
  - Modo simulado: SimuladorPlanta determinista (sin servidor OPC-UA).

El nodeId viaja en la metadata del MetricEvent (ADR-0001).
"""
from __future__ import annotations

import logging
import os

from core.adapters.base import BaseTelemetryAdapter

logger = logging.getLogger(__name__)

# NodeIds típicos de un servidor OPC-UA de planta (ilustrativos)
SENSORES: list[dict] = [
    {
        "id": "nivel_estanque_1", "nombre": "Nivel Estanque 1",
        "node_id": "ns=2;s=Planta.Estanque1.Nivel", "unidad": "%",
        "base": 62.0, "amplitud": 22.0,
        "umbral_warn": 79.0, "umbral_critico": 83.0,
    },
    {
        "id": "rpm_turbina_1", "nombre": "RPM Turbina 1",
        "node_id": "ns=2;s=Planta.Turbina1.RPM", "unidad": "rpm",
        "base": 3400.0, "amplitud": 260.0,
        "umbral_warn": 3600.0, "umbral_critico": 3650.0,
    },
]


class OpcUaTelemetryAdapter(BaseTelemetryAdapter):
    """TelemetryPort sobre OPC-UA; sin endpoint configurado usa SimuladorPlanta."""

    SENSORES = SENSORES

    def __init__(self, endpoint: str | None = None, intervalo_s: float = 5.0, **kw):
        super().__init__(intervalo_s=intervalo_s, **kw)
        self._endpoint = endpoint if endpoint is not None else os.environ.get("AGENTDESK_OPCUA_ENDPOINT", "")
        self._cliente  = None   # asyncua.Client (lazy, fase de conexión real)

    def protocolo(self) -> str:
        return "opcua" if self._endpoint else "simulador"

    def _leer_valor(self, sensor: dict) -> float:
        if not self._endpoint:
            return self._simulador.leer(sensor)
        return self._leer_nodo(sensor)

    def _leer_nodo(self, sensor: dict) -> float:
        """
        Lectura real de un nodeId (fase de conexión a servidor OPC-UA).
        asyncua es async-first: la integración completa reemplazará el
        polling por suscripciones de datos (DataChange) en `ciclo()`.
        Si falta la librería, degrada al simulador con aviso.
        """
        try:
            import asyncua  # noqa: F401
        except ImportError:
            logger.warning("asyncua no instalado — sensor '%s' en modo simulador.", sensor["id"])
            return self._simulador.leer(sensor)

        raise NotImplementedError(
            "Conexión OPC-UA real pendiente de la fase de planta: requiere "
            "endpoint accesible y mapeo de nodeIds definitivo (ver ADR-0004)."
        )
