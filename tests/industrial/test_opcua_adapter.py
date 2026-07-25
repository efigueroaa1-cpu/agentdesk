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
        """El detalle OPC-UA (nodeId) viaja en metadata, no en el contrato.

        NodeIds reales del Prosys OPC UA Simulation Server (2026-07-25):
        ns=3 es el namespace Simulation (senales vivas ±2.0).
        """
        evento = OpcUaTelemetryAdapter(endpoint="").leer("nivel_estanque_1")[0]
        self.assertIsInstance(evento, MetricEvent)
        self.assertEqual(evento.metadata["node_id"], "ns=3;i=1004")
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


class TestOpcUaLecturaReal(unittest.TestCase):
    """Lectura real via asyncua.sync (2026-07-25, cierre del esqueleto ADR-0004).

    Con endpoint configurado el adaptador NUNCA degrada al simulador: lee el
    nodeId real y transforma la senal cruda de Prosys (±2.0) al rango fisico
    del sensor (base ± amplitud); un fallo de conexion lanza ConnectionError
    (el ciclo lo maneja via _reconectar, ADR-0012) en vez de inventar datos.
    """

    ENDPOINT = "opc.tcp://localhost:53530/OPCUA/SimulationServer"

    def _adaptador_con_cliente_mock(self, valor_crudo):
        from unittest.mock import MagicMock, patch

        nodo = MagicMock()
        nodo.read_value.return_value = valor_crudo
        cliente = MagicMock()
        cliente.get_node.return_value = nodo
        parche = patch("asyncua.sync.Client", return_value=cliente)
        return parche, cliente

    def test_05_lectura_real_transforma_al_rango_fisico(self):
        """Senal cruda 0.0 (centro de ±2) -> valor base del sensor."""
        parche, cliente = self._adaptador_con_cliente_mock(0.0)
        with parche:
            a = OpcUaTelemetryAdapter(endpoint=self.ENDPOINT)
            evento = a.leer("nivel_estanque_1")[0]
        self.assertAlmostEqual(evento.valor, 62.0)          # base
        cliente.connect.assert_called_once()

    def test_06_extremo_de_senal_llega_al_borde_de_amplitud(self):
        """Senal cruda +2.0 -> base + amplitud (84% para nivel_estanque_1)."""
        parche, _ = self._adaptador_con_cliente_mock(2.0)
        with parche:
            a = OpcUaTelemetryAdapter(endpoint=self.ENDPOINT)
            evento = a.leer("nivel_estanque_1")[0]
        self.assertAlmostEqual(evento.valor, 84.0)          # base + amplitud

    def test_07_cliente_se_reusa_entre_lecturas(self):
        """La conexion es lazy y persistente: 2 lecturas, 1 solo connect()."""
        parche, cliente = self._adaptador_con_cliente_mock(0.0)
        with parche:
            a = OpcUaTelemetryAdapter(endpoint=self.ENDPOINT)
            a.leer("nivel_estanque_1")
            a.leer("rpm_turbina_1")
        cliente.connect.assert_called_once()
        self.assertEqual(cliente.get_node.call_count, 2)

    def test_08_fallo_de_conexion_no_degrada_a_simulador(self):
        """Endpoint configurado + servidor caido = ConnectionError, NUNCA
        datos inventados del simulador (integridad industrial, ADR-0021)."""
        from unittest.mock import MagicMock, patch

        cliente = MagicMock()
        cliente.connect.side_effect = OSError("conexion rechazada")
        with patch("asyncua.sync.Client", return_value=cliente):
            a = OpcUaTelemetryAdapter(endpoint=self.ENDPOINT)
            with self.assertRaises(ConnectionError):
                a.leer("nivel_estanque_1")

    def test_09_reconectar_descarta_el_cliente_roto(self):
        """_reconectar() cierra y descarta el cliente para forzar uno nuevo."""
        parche, cliente = self._adaptador_con_cliente_mock(0.0)
        with parche:
            a = OpcUaTelemetryAdapter(endpoint=self.ENDPOINT)
            a.leer("nivel_estanque_1")
            asyncio.run(a._reconectar())
        cliente.disconnect.assert_called_once()
        self.assertIsNone(a._cliente)


if __name__ == "__main__":
    unittest.main()
