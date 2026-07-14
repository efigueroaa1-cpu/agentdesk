# -*- coding: utf-8 -*-
"""
tests/industrial/test_mqtt_adapter.py — Contrato del adaptador MQTT (Fase 6).

Incluye el criterio de soberanía OT: alternar simulador⇄broker por variable
de entorno mantiene el flujo de telemetría (mismo MetricEvent) inalterado.
"""
import asyncio
import unittest

from core.adapters.mqtt_adapter import SENSORES, MqttTelemetryAdapter
from core.ports.telemetry_port import MetricEvent, TelemetryPort


class TestMqttAdapter(unittest.TestCase):

    def test_01_contrato_telemetry_port(self):
        self.assertIsInstance(MqttTelemetryAdapter(), TelemetryPort)

    def test_02_protocolo_conmuta_por_configuracion(self):
        """Sin broker → simulador; con broker → mqtt. Solo cambia la etiqueta."""
        sim  = MqttTelemetryAdapter(broker="")
        real = MqttTelemetryAdapter(broker="192.168.1.50:1883")
        self.assertEqual(sim.protocolo(), "simulador")
        self.assertEqual(real.protocolo(), "mqtt")
        self.assertEqual({f["protocolo"] for f in sim.fuentes()},  {"simulador"})
        self.assertEqual({f["protocolo"] for f in real.fuentes()}, {"mqtt"})

    def test_03_flujo_identico_en_ambos_modos(self):
        """El MetricEvent tiene la MISMA forma con simulador o broker (criterio Fase 6)."""
        for broker in ("", "192.168.1.50:1883"):
            adaptador = MqttTelemetryAdapter(broker=broker)
            evento = adaptador.leer("temp_horno_1")[0]
            self.assertIsInstance(evento, MetricEvent)
            self.assertEqual(evento.tipo, "lectura_sensor")
            self.assertEqual(evento.unidad, "°C")
            self.assertEqual(evento.metadata["topic"], "planta/horno1/temperatura")
            self.assertEqual(set(evento.to_dict().keys()),
                             {"fuente", "tipo", "valor", "unidad", "ts", "nivel", "metadata"})

    def test_04_ciclo_simulado_emite_todos_los_sensores(self):
        recibidos: list[MetricEvent] = []

        async def escenario():
            adaptador = MqttTelemetryAdapter(broker="", intervalo_s=0)

            async def captura(e: MetricEvent) -> None:
                recibidos.append(e)

            adaptador.suscribir(captura)
            await adaptador.ciclo(max_ticks=3)

        asyncio.run(escenario())
        self.assertEqual(len(recibidos), 3 * len(SENSORES))
        self.assertEqual({e.fuente for e in recibidos}, {s["id"] for s in SENSORES})


if __name__ == "__main__":
    unittest.main()
