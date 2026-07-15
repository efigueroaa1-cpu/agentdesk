# -*- coding: utf-8 -*-
"""
tests/harnesses/test_memoria_harness.py — ContextHarness (Fase 11, ADR-0009).

Criterio de éxito: un agente con el ContextHarness activo recupera
automáticamente fragmentos de conversaciones PASADAS (persistidas en
auditoria_ia) semánticamente relacionados con el mensaje actual, respetando
un presupuesto de tokens y sin romper la conversación si algo falla.

Usa una base SQLite temporal — no toca la DB real del usuario.
"""
import tempfile
import unittest
from pathlib import Path

import core.database as db
from core.services import audit_service
from core.services.harness_service import ContextHarness, HarnessService, harness_service


class TestContextHarness(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "harness_test.db")
        audit_service.registrar_interaccion(
            tipo="chat", agente_id="agente.mantenimiento",
            prompt="¿Cuál es el torque recomendado para el motor XJ-200?",
            respuesta="El torque recomendado para el motor XJ-200 es de 45 Nm.",
            user_id="op.planta",
        )
        audit_service.registrar_interaccion(
            tipo="chat", agente_id="agente.mantenimiento",
            prompt="¿Cómo se agenda una capacitación de RRHH?",
            respuesta="Las capacitaciones de RRHH se agendan desde el portal interno.",
            user_id="op.planta",
        )

    def test_01_recupera_fragmento_semanticamente_relacionado(self):
        """Pregunta similar a una pasada -> el fragmento correcto queda inyectado."""
        harness = ContextHarness()
        harness.attach("agente.mantenimiento", {})
        resultado = harness.apply_hooks("pre", {
            "agente_id": "agente.mantenimiento",
            "mensaje": "recuérdame el torque del motor XJ-200",
        })
        extra = resultado.get("memoria_semantica", "")
        self.assertIn("torque", extra.lower())
        self.assertNotIn("capacitación", extra.lower(),
                          "Un tema no relacionado (RRHH) no debe colarse en el contexto")

    def test_02_sin_agente_o_mensaje_no_hace_nada(self):
        harness = ContextHarness()
        harness.attach("agente.mantenimiento", {})
        resultado = harness.apply_hooks("pre", {"agente_id": "agente.mantenimiento", "mensaje": ""})
        self.assertNotIn("memoria_semantica", resultado)

    def test_03_presupuesto_de_tokens_limita_el_contexto(self):
        """Un presupuesto minúsculo debe truncar o vaciar el contexto inyectado."""
        harness = ContextHarness()
        harness.attach("agente.mantenimiento", {"presupuesto_tokens_contexto": 1})
        resultado = harness.apply_hooks("pre", {
            "agente_id": "agente.mantenimiento",
            "mensaje": "torque del motor XJ-200",
        })
        extra = resultado.get("memoria_semantica", "")
        self.assertLessEqual(len(extra.encode("utf-8")), 200,
                              "Presupuesto de 1 token no debe permitir fragmentos largos")

    def test_04_post_hook_es_no_op(self):
        harness = ContextHarness()
        harness.attach("agente.mantenimiento", {})
        resultado = harness.apply_hooks("post", {"respuesta": "sin cambios"})
        self.assertEqual(resultado["respuesta"], "sin cambios")


class TestHarnessServiceBestEffort(unittest.IsolatedAsyncioTestCase):

    async def test_05_sin_harnesses_configurados_no_hace_nada(self):
        extra = await harness_service.aplicar_pre([], "agente.mantenimiento", "cualquier mensaje")
        self.assertEqual(extra, "")

    async def test_06_harness_desconocido_se_ignora_sin_romper(self):
        extra = await harness_service.aplicar_pre(
            ["harness_inexistente"], "agente.mantenimiento", "cualquier mensaje",
        )
        self.assertEqual(extra, "")

    async def test_07_memoria_integrado_via_harness_service(self):
        extra = await harness_service.aplicar_pre(
            ["memoria"], "agente.mantenimiento", "necesito el torque del XJ-200",
        )
        self.assertIn("torque", extra.lower())

    async def test_08_harness_roto_no_propaga_excepcion(self):
        """Si un HAT lanza durante el hook, aplicar_pre lo absorbe (best-effort)."""
        class _HarnessRoto:
            nombre = "roto"
            def attach(self, *a, **kw): pass
            def detach(self): pass
            def apply_hooks(self, *a, **kw): raise RuntimeError("boom")

        svc = HarnessService()
        svc._REGISTRO = {**HarnessService._REGISTRO, "roto": _HarnessRoto}
        extra = await svc.aplicar_pre(["roto"], "agente.mantenimiento", "mensaje")
        self.assertEqual(extra, "")


if __name__ == "__main__":
    unittest.main()
