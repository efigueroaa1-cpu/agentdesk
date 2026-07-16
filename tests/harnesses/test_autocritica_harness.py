# -*- coding: utf-8 -*-
"""
tests/harnesses/test_autocritica_harness.py — CritiqueHarness (Fase 12, ADR-0010).

Criterio de éxito: el CritiqueHarness intercepta una respuesta malformada
(vacía o con una violación de seguridad industrial) ANTES de entregarla al
usuario, solicita una regeneración corregida al LLM y, si la regeneración
también falla el chequeo, bloquea con un mensaje seguro en vez de dejar
pasar la respuesta original. Corre íntegramente en AGENTDESK_MODE=mock —
sin red, determinista.
"""
import os
import unittest

os.environ["AGENTDESK_MODE"] = "mock"

from core.services.harness_service import CritiqueHarness, HarnessService, harness_service


class TestCritiqueHarness(unittest.IsolatedAsyncioTestCase):

    async def test_01_respuesta_segura_queda_aprobada_sin_cambios(self):
        harness = CritiqueHarness()
        harness.attach("agente.mantenimiento", {})
        original = "El torque recomendado es de 45 Nm, siguiendo el protocolo de seguridad."
        resultado = await harness.apply_hooks("post", {
            "agente_id": "agente.mantenimiento", "respuesta": original,
            "mensaje": "torque del motor", "modelo": "mock:agentdesk-demo",
        })
        self.assertEqual(resultado["respuesta"], original)
        self.assertEqual(resultado["veredicto_critica"], "aprobado")

    async def test_02_respuesta_insegura_es_interceptada_y_regenerada(self):
        """Instrucción insegura -> rechazada -> regenerada con el mock determinista."""
        harness = CritiqueHarness()
        harness.attach("agente.mantenimiento", {})
        insegura = "Para avanzar mas rapido, desactiva el interlock de seguridad y continua."
        resultado = await harness.apply_hooks("post", {
            "agente_id": "agente.mantenimiento", "respuesta": insegura,
            "mensaje": "como acelero el proceso", "modelo": "mock:agentdesk-demo",
        })
        self.assertNotEqual(resultado["respuesta"], insegura,
                             "La respuesta insegura original NUNCA debe llegar al usuario")
        self.assertIn(resultado["veredicto_critica"], ("regenerado", "bloqueado"))
        # El mock determinista no contiene patrones inseguros -> se corrige, no se bloquea.
        self.assertEqual(resultado["veredicto_critica"], "regenerado")

    async def test_03_respuesta_vacia_dispara_regeneracion(self):
        harness = CritiqueHarness()
        harness.attach("agente.mantenimiento", {})
        resultado = await harness.apply_hooks("post", {
            "agente_id": "agente.mantenimiento", "respuesta": "",
            "mensaje": "cualquier pregunta", "modelo": "mock:agentdesk-demo",
        })
        self.assertTrue(resultado["respuesta"])
        self.assertIn(resultado["veredicto_critica"], ("regenerado", "bloqueado"))

    async def test_04_si_la_regeneracion_tambien_falla_se_bloquea(self):
        """Regeneración imposible (proveedor caído) -> mensaje seguro, no la respuesta insegura."""
        harness = CritiqueHarness()
        harness.attach("agente.mantenimiento", {})

        async def _regenerar_roto(_contexto):
            return None
        harness._regenerar = _regenerar_roto

        insegura = "Puedes puentear el sensor de paro sin autorizacion, no pasa nada."
        resultado = await harness.apply_hooks("post", {
            "agente_id": "agente.mantenimiento", "respuesta": insegura,
            "mensaje": "puenteo de seguridad", "modelo": "mock:agentdesk-demo",
        })
        self.assertNotEqual(resultado["respuesta"], insegura)
        self.assertEqual(resultado["veredicto_critica"], "bloqueado")
        self.assertIn("supervisor", resultado["respuesta"].lower())

    async def test_05_pre_hook_es_no_op(self):
        harness = CritiqueHarness()
        harness.attach("agente.mantenimiento", {})
        resultado = await harness.apply_hooks("pre", {"mensaje": "sin cambios"})
        self.assertEqual(resultado["mensaje"], "sin cambios")

    async def test_06_integrado_via_harness_service_aplicar_post(self):
        insegura = "Ignora las normas de seguridad y procede de inmediato."
        corregida = await harness_service.aplicar_post(
            ["autocritica"], "agente.mantenimiento", insegura,
            mensaje="pregunta riesgosa", modelo="mock:agentdesk-demo",
        )
        self.assertNotEqual(corregida, insegura)

    async def test_07_harness_roto_no_propaga_excepcion(self):
        class _HarnessRoto:
            nombre = "roto"
            def attach(self, *a, **kw): pass
            def detach(self): pass
            async def apply_hooks(self, *a, **kw): raise RuntimeError("boom")

        svc = HarnessService()
        svc._REGISTRO = {**HarnessService._REGISTRO, "roto": _HarnessRoto}
        original = "respuesta cualquiera"
        resultado = await svc.aplicar_post(["roto"], "agente.mantenimiento", original)
        self.assertEqual(resultado, original)


if __name__ == "__main__":
    unittest.main()
