# -*- coding: utf-8 -*-
"""
tests/resilience/test_llm_resilience_wired.py — Resiliencia Cognitiva
conectada al camino real (Fase 19, ADR-0017).

Criterio de éxito de la fase: el sistema completa una TAREA simulando la
caída del proveedor primario, activa automáticamente el fallback y
registra el cambio de proveedor y el costo de tokens en la auditoría
forense.

Diferencia con tests/resilience/test_llm_fallback.py (Fase 8): ese archivo
prueba LlmService AISLADO. Este prueba que el chat/tarea REAL de un agente
(core/orchestrator.py -> core/services/orchestrator_service.py) pasa de
verdad por esa cadena — el hallazgo real de la Fase 19 fue que, hasta
ahora, no lo hacía.

Corre en AGENTDESK_MODE=mock — sin red, determinista. Usa una base SQLite
temporal — no toca la DB real del usuario.
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


# Reporte minimo que aprueba los 4 guardrails cuando raw_data trae
# _es_texto_externo=True (mismo patron que
# tests/observability/test_otel_and_forensics.py::test_10).
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


class TestFallbackRealEnTarea(unittest.IsolatedAsyncioTestCase):
    """Criterio de éxito de la Fase 19, exercitado end-to-end."""

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "llm_resilience_wired_test.db")

    def setUp(self):
        # Circuitos limpios entre tests -- llm_service es un singleton de proceso.
        for cb in llm_service._circuitos.values():
            cb.fallos_consecutivos = 0
            cb.abierto_hasta = 0.0

    async def test_01_tarea_completa_pese_a_caida_del_proveedor_primario(self):
        """
        El agente esta configurado con groq (primario). Groq "cae" (5xx
        simulado); la cadena debe saltar a gemini automaticamente y la
        tarea debe completarse -- sin que nadie tenga que reconfigurar
        nada a mano.
        """
        agente = _crear_agente("Agente Finanzas", "groq:llama-3.3-70b-versatile")
        orq = _OrqFake({"agente.finanzas": agente})
        svc = OrchestratorService(
            get_orquestador=lambda: orq, get_bridge=lambda: None,
            broadcast=_broadcast_noop,
        )

        async def _generar_con_fallo_groq(model_id, prompt, temperatura=0.4, prioridad=2):
            proveedor = model_id.split(":", 1)[0]
            if proveedor == "groq":
                raise ConnectionError("HTTP 503 en groq (simulado)")
            return {
                "texto": _REPORTE_VALIDO_JSON,
                "tokens_entrada": 42, "tokens_salida": 18,
                "tokens_total": 60, "tokens_exactos": True,
            }

        with patch.object(llm_service, "_generar_con_uso", side_effect=_generar_con_fallo_groq):
            resultado = await svc.ejecutar_tarea(
                "agente.finanzas", "informe_financiero",
                datos_extra="Ventas Q1: 100. Ventas Q2: 150.",
                user_id="op.finanzas",
            )

        # 1. La tarea se completo -- NO quedo en _api_error ni fue abortada.
        self.assertTrue(resultado["ok"], f"La tarea no se completo: {resultado}")
        self.assertIn("resultado", resultado)
        self.assertEqual(resultado["resultado"]["resumen"], "todo bien")

        # 2. El fallback fue automatico: el agente termino usando gemini,
        # no groq (que "cayo"), sin ninguna intervencion manual.
        self.assertEqual(agente.ultimo_proveedor_llm, "gemini")
        self.assertTrue(llm_service._circuitos["groq"].fallos_consecutivos >= 1,
                        "El fallo de groq debe quedar registrado en su circuito")

    async def test_02_auditoria_registra_proveedor_real_y_tokens(self):
        """
        Criterio de éxito: el cambio de proveedor Y el costo de tokens
        quedan en auditoria_ia -- no solo "la tarea funciono", sino que
        queda trazable POR QUE proveedor respondio y CUANTO costo.
        """
        agente = _crear_agente("Agente Finanzas", "groq:llama-3.3-70b-versatile")
        orq = _OrqFake({"agente.finanzas": agente})
        svc = OrchestratorService(
            get_orquestador=lambda: orq, get_bridge=lambda: None,
            broadcast=_broadcast_noop,
        )

        async def _generar_con_fallo_groq(model_id, prompt, temperatura=0.4, prioridad=2):
            proveedor = model_id.split(":", 1)[0]
            if proveedor == "groq":
                raise ConnectionError("HTTP 503 en groq (simulado)")
            return {
                "texto": _REPORTE_VALIDO_JSON,
                "tokens_entrada": 100, "tokens_salida": 25,
                "tokens_total": 125, "tokens_exactos": True,
            }

        with patch.object(llm_service, "_generar_con_uso", side_effect=_generar_con_fallo_groq):
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
        self.assertEqual(fila["proveedor"], "gemini",
                         "La auditoria debe reflejar el proveedor que RESPONDIO, no el configurado")
        self.assertEqual(fila["costo_estimado"], 125,
                         "El conteo de tokens debe ser el EXACTO reportado por el proveedor")
        self.assertTrue(fila["tokens_exactos"],
                        "tokens_exactos debe ser True: no es una estimacion chars/4")
        self.assertGreater(fila["costo_usd_estimado"], 0,
                           "El costo USD estimado debe calcularse a partir de tokens reales")


if __name__ == "__main__":
    unittest.main()
