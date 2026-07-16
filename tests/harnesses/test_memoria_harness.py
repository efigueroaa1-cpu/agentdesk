# -*- coding: utf-8 -*-
"""
tests/harnesses/test_memoria_harness.py — ContextHarness (Fase 11/12, ADR-0009/0010).

Criterio de éxito: un agente con el ContextHarness activo recupera
automáticamente fragmentos de conversaciones PASADAS (persistidas en
auditoria_ia) semánticamente relacionados con el mensaje actual, respetando
un presupuesto de tokens, AISLADAS POR USER_ID (ADR-0010: un Operador A
jamás recibe recuerdos de un Operador B), y sin romper la conversación si
algo falla.

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
            prompt="¿Cual es el torque recomendado para el motor XJ-200?",
            respuesta="El torque recomendado para el motor XJ-200 es de 45 Nm.",
            user_id="op.planta.A",
        )
        audit_service.registrar_interaccion(
            tipo="chat", agente_id="agente.mantenimiento",
            prompt="¿Cual es el torque recomendado para el motor XJ-200?",
            respuesta="Para el operador B, el torque documentado es de 60 Nm (linea distinta).",
            user_id="op.planta.B",
        )
        audit_service.registrar_interaccion(
            tipo="chat", agente_id="agente.mantenimiento",
            prompt="¿Como se agenda una capacitacion de RRHH?",
            respuesta="Las capacitaciones de RRHH se agendan desde el portal interno.",
            user_id="op.planta.A",
        )

    async def test_01_recupera_fragmento_semanticamente_relacionado(self):
        """Pregunta similar a una pasada -> el fragmento correcto queda inyectado."""
        harness = ContextHarness()
        harness.attach("agente.mantenimiento", {})
        resultado = await harness.apply_hooks("pre", {
            "agente_id": "agente.mantenimiento",
            "mensaje": "recuerdame el torque del motor XJ-200",
            "user_id": "op.planta.A",
        })
        extra = resultado.get("memoria_semantica", "")
        self.assertIn("45 nm", extra.lower())
        self.assertNotIn("capacitacion", extra.lower(),
                          "Un tema no relacionado (RRHH) no debe colarse en el contexto")

    async def test_02_sin_agente_o_mensaje_no_hace_nada(self):
        harness = ContextHarness()
        harness.attach("agente.mantenimiento", {})
        resultado = await harness.apply_hooks("pre", {
            "agente_id": "agente.mantenimiento", "mensaje": "", "user_id": "op.planta.A",
        })
        self.assertNotIn("memoria_semantica", resultado)

    async def test_03_presupuesto_de_tokens_limita_el_contexto(self):
        """Un presupuesto minúsculo debe truncar o vaciar el contexto inyectado."""
        harness = ContextHarness()
        harness.attach("agente.mantenimiento", {"presupuesto_tokens_contexto": 1})
        resultado = await harness.apply_hooks("pre", {
            "agente_id": "agente.mantenimiento",
            "mensaje": "torque del motor XJ-200",
            "user_id": "op.planta.A",
        })
        extra = resultado.get("memoria_semantica", "")
        self.assertLessEqual(len(extra.encode("utf-8")), 200,
                              "Presupuesto de 1 token no debe permitir fragmentos largos")

    async def test_04_post_hook_es_no_op(self):
        harness = ContextHarness()
        harness.attach("agente.mantenimiento", {})
        resultado = await harness.apply_hooks("post", {"respuesta": "sin cambios"})
        self.assertEqual(resultado["respuesta"], "sin cambios")

    async def test_05_sin_user_id_no_entrega_memoria_fail_closed(self):
        """ADR-0010: sin user_id explicito, NUNCA se cae a buscar por agente solamente."""
        harness = ContextHarness()
        harness.attach("agente.mantenimiento", {})
        resultado = await harness.apply_hooks("pre", {
            "agente_id": "agente.mantenimiento",
            "mensaje": "torque del motor XJ-200",
        })
        self.assertNotIn("memoria_semantica", resultado)

    async def test_06_aislamiento_operador_a_no_ve_recuerdos_de_b(self):
        """Mismo agente, misma pregunta, DOS usuarios -> memorias distintas."""
        harness = ContextHarness()

        harness.attach("agente.mantenimiento", {})
        resultado_a = await harness.apply_hooks("pre", {
            "agente_id": "agente.mantenimiento",
            "mensaje": "torque del motor XJ-200",
            "user_id": "op.planta.A",
        })
        harness.attach("agente.mantenimiento", {})
        resultado_b = await harness.apply_hooks("pre", {
            "agente_id": "agente.mantenimiento",
            "mensaje": "torque del motor XJ-200",
            "user_id": "op.planta.B",
        })

        extra_a = resultado_a.get("memoria_semantica", "")
        extra_b = resultado_b.get("memoria_semantica", "")
        self.assertIn("45 nm", extra_a.lower())
        self.assertIn("60 nm", extra_b.lower())
        self.assertNotIn("60 nm", extra_a.lower(),
                          "El Operador A NUNCA debe recibir un recuerdo del Operador B")
        self.assertNotIn("45 nm", extra_b.lower(),
                          "El Operador B NUNCA debe recibir un recuerdo del Operador A")


class TestHarnessServiceBestEffort(unittest.IsolatedAsyncioTestCase):

    async def test_07_sin_harnesses_configurados_no_hace_nada(self):
        extra = await harness_service.aplicar_pre([], "agente.mantenimiento", "cualquier mensaje")
        self.assertEqual(extra, "")

    async def test_08_harness_desconocido_se_ignora_sin_romper(self):
        extra = await harness_service.aplicar_pre(
            ["harness_inexistente"], "agente.mantenimiento", "cualquier mensaje",
            user_id="op.planta.A",
        )
        self.assertEqual(extra, "")

    async def test_09_memoria_integrado_via_harness_service(self):
        extra = await harness_service.aplicar_pre(
            ["memoria"], "agente.mantenimiento", "necesito el torque del XJ-200",
            user_id="op.planta.A",
        )
        self.assertIn("45 nm", extra.lower())

    async def test_10_harness_roto_no_propaga_excepcion(self):
        """Si un HAT lanza durante el hook, aplicar_pre lo absorbe (best-effort)."""
        class _HarnessRoto:
            nombre = "roto"
            def attach(self, *a, **kw): pass
            def detach(self): pass
            async def apply_hooks(self, *a, **kw): raise RuntimeError("boom")

        svc = HarnessService()
        svc._REGISTRO = {**HarnessService._REGISTRO, "roto": _HarnessRoto}
        extra = await svc.aplicar_pre(["roto"], "agente.mantenimiento", "mensaje",
                                       user_id="op.planta.A")
        self.assertEqual(extra, "")


if __name__ == "__main__":
    unittest.main()
