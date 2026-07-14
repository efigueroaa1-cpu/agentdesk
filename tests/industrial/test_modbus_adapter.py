# -*- coding: utf-8 -*-
"""
tests/industrial/test_modbus_adapter.py — Contrato del adaptador Modbus (Fase 6).
Mismo contrato que MQTT: el cambio de protocolo es transparente.
"""
import asyncio
import unittest

from core.adapters.modbus_adapter import SENSORES, ModbusTelemetryAdapter
from core.ports.telemetry_port import MetricEvent, TelemetryPort


class TestModbusAdapter(unittest.TestCase):

    def test_01_contrato_telemetry_port(self):
        self.assertIsInstance(ModbusTelemetryAdapter(), TelemetryPort)

    def test_02_protocolo_conmuta_por_configuracion(self):
        self.assertEqual(ModbusTelemetryAdapter(host="").protocolo(), "simulador")
        self.assertEqual(ModbusTelemetryAdapter(host="10.0.0.7:502").protocolo(), "modbus")

    def test_03_metadata_transporta_el_registro(self):
        """El detalle Modbus (registro/holding) viaja en metadata, no en el contrato."""
        evento = ModbusTelemetryAdapter(host="").leer("temp_reactor_2")[0]
        self.assertIsInstance(evento, MetricEvent)
        self.assertEqual(evento.metadata["registro"], 40001)
        self.assertEqual(evento.unidad, "°C")

    def test_04_ciclo_simulado_emite_todos_los_sensores(self):
        recibidos: list[MetricEvent] = []

        async def escenario():
            adaptador = ModbusTelemetryAdapter(host="", intervalo_s=0)

            async def captura(e: MetricEvent) -> None:
                recibidos.append(e)

            adaptador.suscribir(captura)
            await adaptador.ciclo(max_ticks=3)

        asyncio.run(escenario())
        self.assertEqual(len(recibidos), 3 * len(SENSORES))
        self.assertEqual({e.fuente for e in recibidos}, {s["id"] for s in SENSORES})


if __name__ == "__main__":
    unittest.main()
