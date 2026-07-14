# -*- coding: utf-8 -*-
"""
tests/industrial/test_telemetry_bridge.py — Fase 5: primer dato operativo.

Prueba la cadena industrial completa SIN modificar api.py ni el frontend:
  SimuladorPlanta → MqttTelemetryAdapter → MetricEvent → puente WS →
  ConnectionManager REAL de core/api.py → cliente WebSocket (fake) → UI.

Y la reactividad: un umbral crítico dispara la regla del ReactorIndustrial
(en producción: orchestrator_service.ejecutar_tarea).

Correr:  python -m unittest tests.industrial.test_telemetry_bridge -v
"""
import asyncio
import json
import unittest

from core.adapters.mqtt_adapter import (
    SENSORES,
    MqttTelemetryAdapter,
    SimuladorPlanta,
    instalar_en_app,
)
from core.ports.telemetry_port import MetricEvent, TelemetryPort


class _FakeWebSocket:
    """Cliente WS mínimo: captura lo que el ConnectionManager le envía."""

    def __init__(self):
        self.mensajes: list[dict] = []

    async def send_text(self, texto: str) -> None:
        self.mensajes.append(json.loads(texto))


class _FakeApp:
    """Superficie mínima de FastAPI para instalar_en_app."""

    def __init__(self):
        self.handlers: dict[str, list] = {"startup": [], "shutdown": []}

    def add_event_handler(self, evento, fn):
        self.handlers[evento].append(fn)


class TestAdaptadorIndustrial(unittest.TestCase):

    def test_01_cumple_el_contrato_telemetry_port(self):
        """El adaptador implementa el Protocol TelemetryPort (ADR-0001)."""
        self.assertIsInstance(MqttTelemetryAdapter(), TelemetryPort)

    def test_02_simulador_es_determinista(self):
        """Misma seed y mismo tick → mismo valor (asserts estables)."""
        a, b = SimuladorPlanta(seed=42), SimuladorPlanta(seed=42)
        for _ in range(10):
            a.avanzar(); b.avanzar()
            for sensor in SENSORES:
                self.assertEqual(a.leer(sensor), b.leer(sensor))

    def test_03_lectura_normalizada_a_metric_event(self):
        """leer() entrega MetricEvent con unidad, nivel y metadata OT."""
        adaptador = MqttTelemetryAdapter()
        eventos   = adaptador.leer("temp_horno_1")
        self.assertEqual(len(eventos), 1)
        e = eventos[0]
        self.assertIsInstance(e, MetricEvent)
        self.assertEqual(e.tipo, "lectura_sensor")
        self.assertEqual(e.unidad, "°C")
        self.assertIn(e.nivel, ("info", "warn", "critico"))
        self.assertEqual(e.metadata["topic"], "planta/horno1/temperatura")

    def test_04_primer_dato_operativo_llega_al_ws_de_la_ui(self):
        """
        Cadena completa: ciclo simulado → puente → ConnectionManager REAL
        (core/api.py, sin modificar) → cliente WS. La UI consume ese mismo
        canal vía useMonitorData.js, también sin modificar.
        """
        from core.api import manager   # el manager real de la app

        fake_ws = _FakeWebSocket()

        async def escenario():
            manager._clientes[fake_ws] = "viewer"
            try:
                app = _FakeApp()
                adaptador = instalar_en_app(app, broadcast=manager.broadcast)
                adaptador._intervalo_s = 0            # sin sleeps en el test
                await adaptador.ciclo(max_ticks=12)
            finally:
                manager._clientes.pop(fake_ws, None)

        asyncio.run(asyncio.wait_for(escenario(), timeout=30))

        lecturas = [m for m in fake_ws.mensajes if m.get("tipo") == "telemetria_industrial"]
        self.assertGreaterEqual(len(lecturas), 12 * len(SENSORES),
                                "La UI no recibió las lecturas industriales")
        primera = lecturas[0]
        self.assertIn(primera["fuente"], {s["id"] for s in SENSORES})
        self.assertIsInstance(primera["valor"], (int, float))
        self.assertTrue(primera["ts"])

        alertas = [m for m in fake_ws.mensajes if m.get("tipo") == "alerta_industrial"]
        self.assertGreater(len(alertas), 0,
                           "El simulador debe cruzar el umbral crítico en 12 ticks")
        self.assertIn("Umbral crítico superado", alertas[0]["mensaje"])

    def test_05_umbral_critico_dispara_tarea_reactiva(self):
        """Un cambio en la variable industrial dispara la acción del agente."""
        tareas_disparadas: list[dict] = []

        async def escenario():
            async def broadcast(_msg: dict) -> None:
                pass

            async def ejecutar_tarea(evento: MetricEvent) -> dict:
                tareas_disparadas.append({"fuente": evento.fuente, "valor": evento.valor})
                return {"ok": True}

            app = _FakeApp()
            adaptador = instalar_en_app(app, broadcast=broadcast,
                                        ejecutar_tarea=ejecutar_tarea)
            adaptador._intervalo_s = 0
            await adaptador.ciclo(max_ticks=12)

        asyncio.run(asyncio.wait_for(escenario(), timeout=30))
        self.assertGreater(len(tareas_disparadas), 0,
                           "El umbral crítico debe disparar la tarea reactiva")

    def test_06_alternar_pausa_una_fuente(self):
        """alternar() detiene la difusión de una fuente sin afectar el resto."""
        recibidos: list[MetricEvent] = []

        async def escenario():
            adaptador = MqttTelemetryAdapter(intervalo_s=0)

            async def captura(e: MetricEvent) -> None:
                recibidos.append(e)

            adaptador.suscribir(captura)
            self.assertTrue(adaptador.alternar("presion_linea_a", False))
            await adaptador.ciclo(max_ticks=4)

        asyncio.run(escenario())
        fuentes = {e.fuente for e in recibidos}
        self.assertNotIn("presion_linea_a", fuentes)
        self.assertIn("temp_horno_1", fuentes)


if __name__ == "__main__":
    unittest.main()
