# -*- coding: utf-8 -*-
"""
tests/audit/test_audit_trail.py — Auditoría Forense IA (Fase 9, ADR-0007).

Criterio de éxito: el sistema registra una traza completa de una conversación
en la base de datos de auditoría (user_id, agente, herramientas, tokens,
veredicto de guardrails), sin romper jamás la interacción que registra.

Usa una base SQLite temporal — no toca la DB real del usuario.
"""
import asyncio
import tempfile
import unittest
from pathlib import Path

import core.database as db
from core.services import audit_service
from core.services.orchestrator_service import OrchestratorService


class _AgenteFake:
    nombre = "Analista Fake"
    area   = "finanzas"
    modelo = "mock:agentdesk-demo"

    async def chat_con_herramientas(self, mensaje, **_kw):
        return (f"Respuesta a: {mensaje}", ["buscar_web", "calcular"])

    async def realizar_tarea(self, _tarea):
        return None   # simula abort por guardrails


class _OrqFake:
    def __init__(self):
        self.agentes = {"analista_1": _AgenteFake()}


async def _noop(_msg):
    pass


def _servicio():
    return OrchestratorService(
        get_orquestador=lambda: _OrqFake(),
        get_bridge=lambda: None,
        broadcast=_noop,
    )


class TestAuditoriaForense(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = Path(tempfile.mkdtemp()) / "auditoria_test.db"
        db.init_db(db_path=cls._db_path)

    def test_01_chat_deja_traza_completa(self):
        """Una conversación queda registrada con usuario, tools y tokens."""
        r = asyncio.run(_servicio().chat(
            "Analiza el flujo de caja del proyecto",
            agente_id="analista_1", sesion_id="s-42", user_id="ana.perez",
        ))
        self.assertIn("Respuesta a:", r["respuesta"])

        trazas = audit_service.consultar(user_id="ana.perez")
        self.assertGreaterEqual(len(trazas), 1)
        t = trazas[0]
        self.assertEqual(t["tipo"], "chat")
        self.assertEqual(t["agente_id"], "analista_1")
        self.assertEqual(t["user_id"], "ana.perez")
        self.assertIn("flujo de caja", t["prompt"])
        self.assertIn("Respuesta a:", t["respuesta"])
        self.assertIn("buscar_web", t["herramientas"])
        self.assertGreater(t["costo_estimado"], 0)
        self.assertIn("sesion=s-42", t["contexto"])
        self.assertTrue(t["ts"])

    def test_02_abort_de_guardrails_queda_con_veredicto(self):
        """Una tarea abortada registra veredicto_guardrail=abortado_guardrails."""
        r = asyncio.run(_servicio().ejecutar_tarea(
            "analista_1", "reporte_ventas", user_id="ana.perez"))
        self.assertFalse(r["ok"])

        trazas = audit_service.consultar(agente_id="analista_1")
        veredictos = {t["veredicto_guardrail"] for t in trazas}
        self.assertIn("abortado_guardrails", veredictos)
        abortada = next(t for t in trazas
                        if t["veredicto_guardrail"] == "abortado_guardrails")
        self.assertFalse(abortada["exitoso"])
        self.assertEqual(abortada["tipo"], "tarea")

    def test_03_consulta_filtra_por_usuario(self):
        audit_service.registrar_interaccion(
            tipo="chat", agente_id="a2", prompt="hola", respuesta="ok",
            user_id="otro.usuario")
        self.assertTrue(all(t["user_id"] == "otro.usuario"
                            for t in audit_service.consultar(user_id="otro.usuario")))

    def test_04_resumen_de_costos_agrega_tokens(self):
        resumen = audit_service.resumen_costos(limit_dias=1)
        self.assertGreater(resumen["total"], 0)
        self.assertIn("analista_1", resumen["por_agente"])
        self.assertGreater(resumen["por_agente"]["analista_1"]["tokens"], 0)

    def test_05_auditoria_nunca_rompe_la_interaccion(self):
        """Con la DB rota, registrar retorna None y NO lanza (best-effort)."""
        engine_original = db._engine
        session_original = db._Session
        try:
            # Forzar fallo: sesión que explota
            class _SesionRota:
                def __call__(self):
                    raise RuntimeError("db caida")
            db._Session = _SesionRota()
            resultado = audit_service.registrar_interaccion(
                tipo="chat", agente_id="a", prompt="p", respuesta="r")
            self.assertIsNone(resultado)
        finally:
            db._engine, db._Session = engine_original, session_original


if __name__ == "__main__":
    unittest.main()
