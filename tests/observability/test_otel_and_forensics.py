# -*- coding: utf-8 -*-
"""
tests/observability/test_otel_and_forensics.py — OTEL + Auditoría Forense
(Fase 16, ADR-0014).

Criterio de éxito: el sistema genera un registro forense completo por cada
interacción (prompt, contexto RECUPERADO por los HATs, modelo, veredicto de
CADA guardrail, user_id) y expone métricas en tiempo real (/metrics,
/diagnostico/tracing) sin depender de infraestructura externa.

Corre en AGENTDESK_MODE=mock — sin red. Usa una base SQLite temporal — no
toca la DB real del usuario.
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ["AGENTDESK_MODE"] = "mock"

import core.database as db
from core.services import audit_service
from core.telemetry_otel import medir_paso, spans_recientes


class TestTelemetryOtel(unittest.TestCase):

    def test_01_medir_paso_registra_span_exitoso(self):
        with medir_paso("test.paso_exitoso", agente="demo"):
            pass
        spans = spans_recientes()
        self.assertTrue(any(s["nombre"] == "test.paso_exitoso" and s["exitoso"]
                             for s in spans))

    def test_02_medir_paso_registra_fallo_y_relanza(self):
        with self.assertRaises(ValueError):
            with medir_paso("test.paso_fallido"):
                raise ValueError("boom")
        spans = spans_recientes()
        fallidos = [s for s in spans if s["nombre"] == "test.paso_fallido"]
        self.assertTrue(fallidos)
        self.assertFalse(fallidos[-1]["exitoso"])

    def test_03_medir_paso_registra_duracion_positiva(self):
        import time
        with medir_paso("test.duracion"):
            time.sleep(0.01)
        spans = [s for s in spans_recientes() if s["nombre"] == "test.duracion"]
        self.assertGreater(spans[-1]["duracion_ms"], 0)


class TestMetricasPrometheus(unittest.TestCase):

    def test_04_registrar_interaccion_no_lanza(self):
        from core.metrics_prometheus import registrar_interaccion
        registrar_interaccion(tipo="chat", exitoso=True, agente_id="demo",
                               tokens=120, duracion_s=1.2)

    def test_05_generar_exposicion_contiene_metricas_esperadas(self):
        from core.metrics_prometheus import generar_exposicion, registrar_interaccion
        registrar_interaccion(tipo="chat", exitoso=True, agente_id="demo_metrics",
                               tokens=50, duracion_s=0.5)
        payload, content_type = generar_exposicion()
        texto = payload.decode("utf-8")
        self.assertIn("agentdesk_interacciones_total", texto)
        self.assertIn("agentdesk_tokens_estimados", texto)
        self.assertIn("text/plain", content_type)

    def test_06_endpoint_metrics_responde_publico(self):
        from fastapi.testclient import TestClient
        from core.api import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/metrics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("agentdesk_", r.text)

    def test_07_endpoint_diagnostico_tracing_responde_publico(self):
        from fastapi.testclient import TestClient
        from core.api import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/diagnostico/tracing")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spans", r.json())


class TestAuditoriaForenseCompleta(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "fase16_forense.db")

    def test_08_registro_incluye_contexto_hats_y_guardrails(self):
        id_ = audit_service.registrar_interaccion(
            tipo="chat", agente_id="agente.demo", prompt="pregunta del usuario",
            respuesta="respuesta del agente", user_id="op.planta.A",
            contexto_hats="Recuerdos relevantes: el turno anterior fue X",
            modelo="mock:agentdesk-demo",
            guardrails=[
                {"guardrail": "RecursionGuard", "veredicto": "aprobado"},
                {"guardrail": "ToneGuard", "veredicto": "aprobado"},
                {"guardrail": "GroundingGuard", "veredicto": "aprobado"},
                {"guardrail": "LogicIntegrityFilter", "veredicto": "aprobado"},
            ],
        )
        self.assertIsNotNone(id_)

        trazas = audit_service.consultar(agente_id="agente.demo", user_id="op.planta.A", limit=5)
        fila = trazas[0]
        self.assertIn("Recuerdos relevantes", fila["contexto_hats"])
        self.assertEqual(len(fila["guardrails"]), 4)
        self.assertTrue(all(g["veredicto"] == "aprobado" for g in fila["guardrails"]))

    def test_09_user_id_real_en_db_pero_hasheado_en_el_log(self):
        """DB: user_id real (RBAC/ADR-0010 lo necesitan). Log: solo el hash."""
        with self.assertLogs("core.services.audit_service", level="INFO") as log_ctx:
            audit_service.registrar_interaccion(
                tipo="chat", agente_id="agente.demo",
                prompt="p", respuesta="r", user_id="usuario.sensible.123",
            )
        texto_log = "\n".join(log_ctx.output)
        self.assertNotIn("usuario.sensible.123", texto_log,
                          "El user_id NUNCA debe aparecer en claro en los logs")

        trazas = audit_service.consultar(agente_id="agente.demo",
                                          user_id="usuario.sensible.123", limit=1)
        self.assertEqual(trazas[0]["user_id"], "usuario.sensible.123",
                          "La DB SI debe guardar el user_id real (RBAC/ADR-0010)")


class TestVeredictoDeGuardrails(unittest.IsolatedAsyncioTestCase):

    async def test_10_pipeline_registra_veredicto_de_los_4_guardrails_al_aprobar(self):
        from core.pipeline import PipelineProcessor
        proc = PipelineProcessor("Agente Test")
        # _es_texto_externo=True exime del requisito de 'evidencia' del GroundingGuard.
        raw_data = {"_es_texto_externo": True, "valor_a": 100}
        reporte = {
            "resumen": "todo bien", "kpis": {"a": 1},
            "tabla": [], "evidencia": {},
        }
        resultado = await proc.procesar_con_razon(raw_data, "todo bien", reporte)

        nombres = [v["guardrail"] for v in proc.ultimo_veredicto]
        self.assertEqual(nombres, ["RecursionGuard", "ToneGuard",
                                    "GroundingGuard", "LogicIntegrityFilter"])
        self.assertTrue(all(v["veredicto"] == "aprobado" for v in proc.ultimo_veredicto))

    async def test_11_pipeline_registra_veredicto_parcial_al_abortar(self):
        from core.pipeline import PipelineProcessor
        proc = PipelineProcessor("Agente Test")
        raw_data = {}
        # ToneGuard rechaza coloquialismos de la denylist -> aborta en el paso 2.
        reporte = {
            "resumen": "esto es genial y super basicamente", "kpis": {"a": 1},
            "tabla": [], "evidencia": {},
        }
        resultado = await proc.procesar_con_razon(raw_data, "resp", reporte)

        self.assertIsNotNone(resultado)
        self.assertTrue(resultado.get("_abortado"))
        self.assertEqual(resultado["_guardrail"], "ToneGuard")

        nombres = [v["guardrail"] for v in proc.ultimo_veredicto]
        self.assertEqual(nombres, ["RecursionGuard", "ToneGuard"],
                          "Debe registrar RecursionGuard (aprobado) y ToneGuard (rechazado), nada mas")
        self.assertEqual(proc.ultimo_veredicto[0]["veredicto"], "aprobado")
        self.assertEqual(proc.ultimo_veredicto[-1]["veredicto"], "rechazado")


class TestContextoHatsEndToEnd(unittest.IsolatedAsyncioTestCase):
    """El contexto realmente inyectado por un HAT queda en la auditoria, no solo en el prompt."""

    async def test_12_contexto_hats_capturado_end_to_end(self):
        import asyncio
        import core.orchestrator as orch

        db.init_db(db_path=Path(tempfile.mkdtemp()) / "fase16_e2e.db")
        audit_service.registrar_interaccion(
            tipo="chat", agente_id="agente_e2e",
            prompt="codigo de acceso al panel B",
            respuesta="El codigo del panel B es DELTA-500.",
            user_id="operador.e2e",
        )

        class _ClienteFake:
            pass

        config = {
            "nombre": "Agente E2E", "tipo_ia": "chat", "modelo": "mock:agentdesk-demo",
            "area": "Seguridad", "idioma": "espanol", "harnesses": ["memoria"],
        }
        agente = orch.AgentBase(config, _ClienteFake(), "mock:agentdesk-demo")

        await agente.chat_libre(
            "recuerdas el codigo del panel B?",
            sesion_id="sesion_nueva", agente_id_clave="agente_e2e",
            user_id="operador.e2e",
        )

        self.assertIn("DELTA-500", agente.ultimo_contexto_hats)


if __name__ == "__main__":
    unittest.main()
