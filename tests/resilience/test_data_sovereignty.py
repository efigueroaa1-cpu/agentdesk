# -*- coding: utf-8 -*-
"""
tests/resilience/test_data_sovereignty.py — Soberanía Local (Fase 20, ADR-0018).

Criterio de éxito de la fase (primera mitad): el sistema debe ser capaz de
completar una tarea utilizando el proveedor local simulado (Ollama), SIN
internet -- es decir, con los tres proveedores de nube (groq/gemini/openai)
inalcanzables, la cadena de fallback debe caer en el eslabón local y la
tarea debe completarse igual.

Mismo patrón que tests/resilience/test_llm_resilience_wired.py (Fase 19):
se prueba el camino REAL del agente (core/orchestrator.py ->
OrchestratorService), no LlmService aislado -- así el test no puede pasar
por casualidad si el wiring de Ollama en CADENA_FALLBACK se rompe en algún
punto intermedio.

Corre en AGENTDESK_MODE=mock -- sin red real, determinista.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["AGENTDESK_MODE"] = "mock"

import core.database as db
from core.services import audit_service
from core.services.llm_service import llm_service
from core.services.orchestrator_service import OrchestratorService

_REPORTE_VALIDO_JSON = (
    '{"resumen": "todo bien", "kpis": {"Ventas": 100}, '
    '"tabla": [["Columna1", "Columna2"]], '
    '"evidencia": {"Ventas": "Ventas Q1: 100"}}'
)


class _OrqFake:
    def __init__(self, agentes: dict):
        self.agentes = agentes


def _crear_agente(nombre: str, modelo: str):
    import core.orchestrator as orch

    class _ClienteFake:
        pass

    config = {
        "nombre": nombre, "tipo_ia": "chat", "modelo": modelo,
        "area": "Finanzas", "idioma": "espanol", "prompt_base": f"Eres {nombre}.",
    }
    return orch.AgentBase(config, _ClienteFake(), modelo)


async def _broadcast_noop(_msg: dict) -> None:
    return None


class TestSoberaniaLocalOllama(unittest.IsolatedAsyncioTestCase):
    """Criterio de éxito de la Fase 20 (mitad 1/2), ejercitado end-to-end."""

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "data_sovereignty_test.db")

    def setUp(self):
        for cb in llm_service._circuitos.values():
            cb.fallos_consecutivos = 0
            cb.abierto_hasta = 0.0
            cb.abierto_desde = 0.0

    async def test_01_tarea_se_completa_con_toda_la_nube_caida_via_ollama_local(self):
        """
        Groq, Gemini Y OpenAI "caen" (simulando ausencia total de internet) --
        solo el proveedor local (ollama) responde. La cadena de fallback debe
        alcanzarlo igual y la tarea debe completarse con inteligencia real,
        sin degradar al mock (que solo responde texto deterministico fijo).
        """
        agente = _crear_agente("Agente Finanzas", "groq:llama-3.3-70b-versatile")
        orq = _OrqFake({"agente.finanzas": agente})
        svc = OrchestratorService(
            get_orquestador=lambda: orq, get_bridge=lambda: None,
            broadcast=_broadcast_noop,
        )

        async def _generar_sin_internet(model_id, prompt, temperatura=0.4, prioridad=2):
            proveedor = model_id.split(":", 1)[0]
            if proveedor in ("groq", "gemini", "openai"):
                raise ConnectionError(f"sin conectividad a internet ({proveedor}, simulado)")
            if proveedor == "ollama":
                return {
                    "texto": _REPORTE_VALIDO_JSON,
                    "tokens_entrada": 30, "tokens_salida": 12,
                    "tokens_total": 42, "tokens_exactos": True,
                }
            raise AssertionError(f"proveedor inesperado: {proveedor}")

        with patch.object(llm_service, "_generar_con_uso", side_effect=_generar_sin_internet):
            resultado = await svc.ejecutar_tarea(
                "agente.finanzas", "informe_financiero",
                datos_extra="Ventas Q1: 100. Ventas Q2: 150.",
                user_id="op.finanzas",
            )

        self.assertTrue(resultado["ok"], f"La tarea no se completo: {resultado}")
        self.assertEqual(resultado["resultado"]["resumen"], "todo bien")

        # El proveedor que RESPONDIO fue el local, no el mock -- sigue siendo
        # inteligencia real, solo que sin salir a internet (ver docstring de
        # llm_service.py, seccion Fase 20/ADR-0018).
        self.assertEqual(agente.ultimo_proveedor_llm, "ollama")

        # Los tres proveedores de nube deben haber quedado marcados como
        # caidos -- la resiliencia no "adivino" saltar a ollama, lo alcanzo
        # recorriendo la cadena entera.
        for proveedor in ("groq", "gemini", "openai"):
            self.assertGreaterEqual(
                llm_service._circuitos[proveedor].fallos_consecutivos, 1,
                f"El fallo de {proveedor} debe quedar registrado en su circuito",
            )

    async def test_02_auditoria_registra_proveedor_local_y_tokens(self):
        """La traza forense debe reflejar 'ollama' como proveedor real -- trazable,
        no solo 'la tarea funciono'."""
        agente = _crear_agente("Agente Finanzas", "groq:llama-3.3-70b-versatile")
        orq = _OrqFake({"agente.finanzas": agente})
        svc = OrchestratorService(
            get_orquestador=lambda: orq, get_bridge=lambda: None,
            broadcast=_broadcast_noop,
        )

        async def _generar_sin_internet(model_id, prompt, temperatura=0.4, prioridad=2):
            proveedor = model_id.split(":", 1)[0]
            if proveedor in ("groq", "gemini", "openai"):
                raise ConnectionError(f"sin conectividad a internet ({proveedor}, simulado)")
            return {
                "texto": _REPORTE_VALIDO_JSON,
                "tokens_entrada": 50, "tokens_salida": 20,
                "tokens_total": 70, "tokens_exactos": True,
            }

        with patch.object(llm_service, "_generar_con_uso", side_effect=_generar_sin_internet):
            resultado = await svc.ejecutar_tarea(
                "agente.finanzas", "informe_financiero",
                datos_extra="Ventas Q1: 100. Ventas Q2: 150.",
                user_id="op.finanzas",
            )
        self.assertTrue(resultado["ok"])

        trazas = audit_service.consultar(agente_id="agente.finanzas",
                                          user_id="op.finanzas", limit=5)
        self.assertTrue(trazas, "La tarea completada debe dejar una traza de auditoria")
        fila = trazas[0]
        self.assertEqual(fila["proveedor"], "ollama")
        self.assertTrue(fila["tokens_exactos"])


if __name__ == "__main__":
    unittest.main()
