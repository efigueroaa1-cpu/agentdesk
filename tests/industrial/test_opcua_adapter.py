# -*- coding: utf-8 -*-
"""
tests/industrial/test_opcua_adapter.py — Contrato del adaptador OPC-UA (Fase 6).
Mismo contrato que MQTT: el cambio de protocolo es transparente.
"""
import asyncio
import unittest

from core.adapters.opcua_adapter import SENSORES, OpcUaTelemetryAdapter
from core.ports.telemetry_port import MetricEvent, TelemetryPort


class TestOpcUaAdapter(unittest.TestCase):

    def test_01_contrato_telemetry_port(self):
        self.assertIsInstance(OpcUaTelemetryAdapter(), TelemetryPort)

    def test_02_protocolo_conmuta_por_configuracion(self):
        self.assertEqual(OpcUaTelemetryAdapter(endpoint="").protocolo(), "simulador")
        self.assertEqual(
            OpcUaTelemetryAdapter(endpoint="opc.tcp://10.0.0.9:4840").protocolo(), "opcua")

    def test_03_metadata_transporta_el_node_id(self):
        """El detalle OPC-UA (nodeId) viaja en metadata, no en el contrato."""
        evento = OpcUaTelemetryAdapter(endpoint="").leer("nivel_estanque_1")[0]
        self.assertIsInstance(evento, MetricEvent)
        self.assertEqual(evento.metadata["node_id"], "ns=2;s=Planta.Estanque1.Nivel")
        self.assertEqual(evento.unidad, "%")

    def test_04_ciclo_simulado_emite_todos_los_sensores(self):
        recibidos: list[MetricEvent] = []

        async def escenario():
            adaptador = OpcUaTelemetryAdapter(endpoint="", intervalo_s=0)

            async def captura(e: MetricEvent) -> None:
                recibidos.append(e)

            adaptador.suscribir(captura)
            await adaptador.ciclo(max_ticks=3)

        asyncio.run(escenario())
        self.assertEqual(len(recibidos), 3 * len(SENSORES))
        self.assertEqual({e.fuente for e in recibidos}, {s["id"] for s in SENSORES})


if __name__ == "__main__":
    unittest.main()
