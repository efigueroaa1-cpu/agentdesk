# -*- coding: utf-8 -*-
"""
tests/industrial/test_gemelo_digital.py — Gemelo Digital Operativo
(Fase 23, ADR-0021).

Criterio de éxito de la fase: un cambio simulado en una métrica Modbus
(parada de máquina) genera automáticamente (a) un ajuste en la proyección
de la Curva S y (b) una alerta de riesgo financiero.

También cubre la higiene anti data-poisoning ([INDUSTRIAL-INTEGRITY]): una
lectura físicamente imposible se marca, se audita y NUNCA alimenta el
Gemelo Digital.

Corre sin red y sin PLC real: los eventos se inyectan al historial OT con
la MISMA forma (MetricEvent.to_dict) que producen los adaptadores reales.
Usa una base SQLite temporal — no toca la DB real del usuario.
"""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path

os.environ["AGENTDESK_MODE"] = "mock"
os.environ["AGENTDESK_CPU_MAX_PCT"] = "100"   # tests de logica, no del breaker
os.environ["AGENTDESK_MEM_MAX_PCT"] = "100"

import core.database as db
import core.telemetry_history as th
from core.adapters.modbus_adapter import ModbusTelemetryAdapter, SENSORES
from core.analytics import MotorCorrelacionOT
from core.services.map_reduce_service import MapReduceService
from core.services.queue_service import LocalQueueService
from core.services.risk_analysis_service import RiskAnalysisService
from core.timeutil import utcnow
from datetime import timedelta


SENSOR_BOMBA = next(s for s in SENSORES if s["id"] == "caudal_bomba_5")

PROYECTO_F23 = "planta_norte_f23"


def setUpModule():
    """DB temporal + proyecto Gantt UNA vez para todo el modulo — unittest
    ordena las clases alfabeticamente y mas de una necesita el proyecto."""
    db.init_db(db_path=Path(tempfile.mkdtemp()) / "gemelo_digital_test.db")
    from core.gantt import motor_gantt
    inicio = utcnow() - timedelta(days=5)
    t = motor_gantt.crear_tarea({
        "proyecto_id": PROYECTO_F23, "nombre": "Montaje linea A",
        "inicio_plan": inicio.isoformat(), "duracion_dias": 35.0,
    })
    motor_gantt.actualizar_progreso(t["id"], {"pct_completado": 40.0})


def _evento(sensor_id: str, valor: float, nivel: str = "info") -> dict:
    """Evento con la misma forma que MetricEvent.to_dict() de los adaptadores."""
    return {
        "fuente": sensor_id, "tipo": "lectura_sensor", "valor": valor,
        "unidad": "m³/h", "ts": utcnow().isoformat(), "nivel": nivel,
        "metadata": {"umbral_warn": SENSOR_BOMBA["umbral_warn"],
                     "umbral_critico": SENSOR_BOMBA["umbral_critico"]},
    }


class TestIntegridadFisica(unittest.TestCase):
    """[INDUSTRIAL-INTEGRITY]: rangos min/max contra data poisoning."""

    def setUp(self):
        th.limpiar()

    def test_01_lectura_imposible_se_marca_y_audita(self):
        adaptador = ModbusTelemetryAdapter(host="")
        with self.assertLogs("core.adapters.base", level="WARNING") as cap:
            evento = adaptador._evento_de(SENSOR_BOMBA, 99999.0)
        self.assertTrue(evento.metadata.get("fuera_de_rango_fisico"))
        self.assertEqual(evento.nivel, "critico")
        self.assertTrue(any("AUDITORIA_SEGURIDAD" in m and "fisicamente imposible" in m
                            for m in cap.output))

    def test_02_lectura_envenenada_no_entra_al_historial(self):
        adaptador = ModbusTelemetryAdapter(host="")
        envenenado = adaptador._evento_de(SENSOR_BOMBA, -500.0)
        legitimo   = adaptador._evento_de(SENSOR_BOMBA, 41.0)
        th.registrar_evento(envenenado.to_dict())
        th.registrar_evento(legitimo.to_dict())
        eventos = th.eventos_recientes(fuente="caudal_bomba_5")
        self.assertEqual(len(eventos), 1, "Solo la lectura legitima alimenta el Gemelo")
        self.assertEqual(eventos[0]["valor"], 41.0)

    def test_03_lectura_legitima_no_se_marca(self):
        adaptador = ModbusTelemetryAdapter(host="")
        evento = adaptador._evento_de(SENSOR_BOMBA, 42.5)
        self.assertNotIn("fuera_de_rango_fisico", evento.metadata)


class TestCriterioDeExito(unittest.TestCase):
    """Parada de máquina Modbus → ajuste de Curva S + alerta financiera."""

    PROYECTO = PROYECTO_F23

    def setUp(self):
        th.limpiar()
        self.motor = MotorCorrelacionOT()
        self.motor.vincular(self.PROYECTO, "caudal_bomba_5",
                            rendimiento_nominal=SENSOR_BOMBA["base"])

    def _simular(self, valor: float, n: int = 30):
        for _ in range(n):
            th.registrar_evento(_evento("caudal_bomba_5", valor))

    def test_01_produccion_normal_sin_impacto(self):
        self._simular(42.0)   # bomba al regimen nominal
        p = self.motor.proyeccion_ajustada(self.PROYECTO)
        self.assertGreaterEqual(p["produccion"]["factor"], 0.9)
        self.assertFalse(p["impacto_cronograma"])
        self.assertFalse(p["riesgo_presupuesto"])

    def test_02_parada_de_maquina_ajusta_curva_s_y_alerta_financiera(self):
        """EL CRITERIO DE EXITO, de punta a punta."""
        self._simular(0.0)    # parada de maquina: el caudal cae a cero

        with self.assertLogs("core.analytics", level="ERROR") as cap:
            p = self.motor.proyeccion_ajustada(self.PROYECTO)

        # (a) Ajuste automatico de la proyeccion de la Curva S
        self.assertTrue(p["produccion"]["parada_detectada"])
        self.assertTrue(p["impacto_cronograma"],
                        "La parada debe impactar la fecha de fin proyectada")
        self.assertGreater(p["dias_atraso_proyectados"], 0)
        self.assertGreater(p["fin_proyectado"], p["fin_plan"])
        self.assertLess(p["spi_fisico"], p["curva_s"]["kpis"]["spi"],
                        "El SPI fisico debe caer respecto del SPI reportado")

        # (b) Alerta de riesgo financiero (AUDITORIA_SEGURIDAD)
        self.assertTrue(p["riesgo_presupuesto"])
        self.assertGreater(p["eac_ajustado"], p["curva_s"]["kpis"]["bac"])
        self.assertTrue(any("AUDITORIA_SEGURIDAD" in m and "riesgo financiero" in m
                            for m in cap.output))

    def test_03_recuperacion_limpia_el_riesgo(self):
        """Tras la parada, la bomba vuelve: la proyeccion se normaliza sola."""
        self._simular(0.0, n=5)
        self._simular(42.0, n=60)   # la ventana reciente domina
        p = self.motor.proyeccion_ajustada(self.PROYECTO)
        self.assertFalse(p["produccion"]["parada_detectada"])
        self.assertFalse(p["riesgo_presupuesto"])


class _AgenteAnalistaFake:
    nombre = "Analista de Riesgos"

    def __init__(self):
        self.prompts_recibidos: list[str] = []

    async def chat_libre(self, mensaje, **kw):
        self.prompts_recibidos.append(mensaje)
        await asyncio.sleep(0.05)
        return "Riesgo operacional: caudal detenido en el segmento analizado."


class TestAnalistaDeRiesgos(unittest.IsolatedAsyncioTestCase):
    """Alertas proactivas: screening determinista + Map-Reduce cognitivo."""

    PROYECTO = PROYECTO_F23

    def setUp(self):
        th.limpiar()
        self.analista = _AgenteAnalistaFake()
        orq = type("O", (), {"agentes": {"analista.riesgos": self.analista}})()
        mr = MapReduceService(get_orquestador=lambda: orq,
                              queue_service=LocalQueueService())
        self.svc = RiskAnalysisService(get_orquestador=lambda: orq,
                                       map_reduce_service=mr)
        from core.analytics import motor_correlacion
        motor_correlacion._vinculos.pop(self.PROYECTO, None)
        motor_correlacion.vincular(self.PROYECTO, "caudal_bomba_5",
                                   rendimiento_nominal=SENSOR_BOMBA["base"])

    async def test_01_parada_dispara_alerta_y_evaluacion_paralela(self):
        for _ in range(200):
            th.registrar_evento(_evento("caudal_bomba_5", 0.0))

        with self.assertLogs("core.services.risk_analysis_service", level="ERROR") as cap:
            r = await self.svc.analizar(self.PROYECTO,
                                        analista_id="analista.riesgos",
                                        user_id="op.riesgos")

        self.assertEqual(r["metricas_evaluadas"], 200)
        self.assertTrue(any(a["tipo"] == "parada_maquina" for a in r["anomalias"]))
        self.assertTrue(r["riesgo_financiero"])
        self.assertTrue(any("AUDITORIA_SEGURIDAD" in m and "presupuesto" in m
                            for m in cap.output))
        # Capa cognitiva: chunks evaluados EN PARALELO (hilos distintos)
        self.assertIsNotNone(r["evaluacion_llm"])
        self.assertGreaterEqual(r["evaluacion_llm"]["total_workers"], 2)
        self.assertGreaterEqual(len(r["evaluacion_llm"]["hilos_usados"]), 2)
        # Cada worker recibio SU chunk (prompts distintos por segmento)
        self.assertGreaterEqual(len(set(self.analista.prompts_recibidos)), 2)

    async def test_02_sin_anomalias_no_alerta(self):
        for _ in range(100):
            th.registrar_evento(_evento("caudal_bomba_5", 42.0))
        r = await self.svc.analizar(self.PROYECTO, user_id="op.riesgos")
        self.assertEqual(r["anomalias"], [])
        self.assertFalse(r["riesgo_financiero"])


if __name__ == "__main__":
    unittest.main()
