# -*- coding: utf-8 -*-
"""
tests/collaboration/test_delegation.py — Delegación Cognitiva Speak/Listen
(Fase 13, ADR-0011).

Criterio de éxito: un Agente A puede pedirle ayuda a un Agente B en tiempo
de ejecución (vía la herramienta consultar_a_otro_agente), y AMBOS lados de
la delegación quedan auditados en auditoria_ia (ADR-0007).

Corre en AGENTDESK_MODE=mock — sin red, determinista. Usa una base SQLite
temporal — no toca la DB real del usuario.
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ["AGENTDESK_MODE"] = "mock"

import core.database as db
from core.services import audit_service
from core.services.delegation_service import DelegationService


class _OrqFake:
    """Orquestador mínimo: solo necesita exponer `.agentes` (dict id -> AgentBase)."""
    def __init__(self, agentes: dict):
        self.agentes = agentes


def _crear_agente(nombre: str, area: str):
    import core.orchestrator as orch

    class _ClienteFake:
        pass

    config = {
        "nombre": nombre, "tipo_ia": "chat", "modelo": "mock:agentdesk-demo",
        "area": area, "idioma": "espanol", "prompt_base": f"Eres {nombre}.",
    }
    return orch.AgentBase(config, _ClienteFake(), "mock:agentdesk-demo")


class TestDelegationService(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "delegacion_test.db")

    def setUp(self):
        self.agente_a = _crear_agente("Agente Finanzas", "Finanzas")
        self.agente_b = _crear_agente("Agente Mantenimiento", "Mantenimiento")
        self.orq = _OrqFake({"agente.finanzas": self.agente_a,
                              "agente.mantenimiento": self.agente_b})
        self.svc = DelegationService(lambda: self.orq)

    async def test_01_speak_a_agente_inexistente(self):
        respuesta = await self.svc.speak("agente.finanzas", "agente.fantasma",
                                          "hola", user_id="op.planta")
        self.assertIn("no existe", respuesta.lower())

    async def test_02_speak_a_uno_mismo_rechazado(self):
        respuesta = await self.svc.speak("agente.finanzas", "agente.finanzas",
                                          "hola", user_id="op.planta")
        self.assertIn("uno mismo", respuesta.lower())

    async def test_03_delegacion_exitosa_retorna_respuesta_del_destino(self):
        respuesta = await self.svc.speak(
            "agente.finanzas", "agente.mantenimiento",
            "cual es el estado del motor XJ-200?", user_id="op.planta",
        )
        self.assertTrue(respuesta)
        self.assertIn("mock", respuesta.lower())   # el mock determinista firma su salida

    async def test_04_ambos_lados_quedan_auditados(self):
        """Criterio de éxito: se conserva la traza de auditoría de AMBOS agentes."""
        await self.svc.speak(
            "agente.finanzas", "agente.mantenimiento",
            "necesito el torque del motor XJ-200", user_id="op.planta",
        )
        trazas_origen  = audit_service.consultar(agente_id="agente.finanzas",
                                                  user_id="op.planta", limit=10)
        trazas_destino = audit_service.consultar(agente_id="agente.mantenimiento",
                                                  user_id="op.planta", limit=10)

        delegaciones_origen  = [t for t in trazas_origen if t.get("tipo") == "delegacion"]
        delegaciones_destino = [t for t in trazas_destino if t.get("tipo") == "delegacion"]

        self.assertTrue(delegaciones_origen, "Falta la traza del lado que DELEGO")
        self.assertTrue(delegaciones_destino, "Falta la traza del lado que RESOLVIO")
        self.assertEqual(delegaciones_origen[0]["contexto"], "delegado")
        self.assertEqual(delegaciones_destino[0]["contexto"], "resuelto")

    async def test_05_listen_usa_chat_libre_no_tool_calling(self):
        """
        Freno estructural anti-ciclos (ADR-0011): el destino responde vía
        chat_libre (sin herramientas), por lo que no puede volver a delegar.
        """
        llamadas = {}
        original = self.agente_b.chat_libre

        async def _chat_libre_espia(*args, **kwargs):
            llamadas["chat_libre"] = True
            return await original(*args, **kwargs)
        self.agente_b.chat_libre = _chat_libre_espia

        async def _chat_con_herramientas_espia(*args, **kwargs):
            llamadas["chat_con_herramientas"] = True
            return "no deberia llamarse", []
        self.agente_b.chat_con_herramientas = _chat_con_herramientas_espia

        await self.svc.speak("agente.finanzas", "agente.mantenimiento",
                              "pregunta cualquiera", user_id="op.planta")

        self.assertTrue(llamadas.get("chat_libre"))
        self.assertNotIn("chat_con_herramientas", llamadas)


class TestHerramientaConsultarAOtroAgente(unittest.IsolatedAsyncioTestCase):
    """Integración vía la superficie de herramientas (core/tools.py)."""

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "delegacion_tool_test.db")

    async def test_06_delegacion_sin_orquestador_no_rompe(self):
        import core.tools as tools
        original = tools._orquestador_ref
        tools.set_orquestador(None)
        try:
            resultado = await tools.ejecutar_herramienta(
                "consultar_a_otro_agente",
                {"agente_id": "agente.mantenimiento", "pregunta": "hola"},
                agente_id_clave="agente.finanzas", user_id="op.planta",
            )
            self.assertIn("no disponible", resultado.lower())
        finally:
            tools.set_orquestador(original)

    async def test_07_delegacion_integrada_via_ejecutar_herramienta(self):
        import core.tools as tools
        agente_a = _crear_agente("Agente Finanzas", "Finanzas")
        agente_b = _crear_agente("Agente Mantenimiento", "Mantenimiento")
        orq = _OrqFake({"agente.finanzas": agente_a, "agente.mantenimiento": agente_b})

        original = tools._orquestador_ref
        tools.set_orquestador(orq)
        try:
            resultado = await tools.ejecutar_herramienta(
                "consultar_a_otro_agente",
                {"agente_id": "agente.mantenimiento", "pregunta": "estado del motor?"},
                agente_id_clave="agente.finanzas", user_id="op.planta",
            )
            self.assertTrue(resultado)
            self.assertIn("mock", resultado.lower())
        finally:
            tools.set_orquestador(original)


if __name__ == "__main__":
    unittest.main()
