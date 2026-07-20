# -*- coding: utf-8 -*-
"""
tests/harnesses/test_memoria_en_realizar_tarea.py — HATs en el lote batch
(2026-07-20).

Hallazgo real: _contexto_harnesses() (ADR-0009/0010) SOLO se invocaba desde
chat_libre/chat_con_herramientas (y sus variantes streaming) — jamas desde
realizar_tarea(), el metodo que usan los 22 agentes de la Opcion Paralelo
(main.py). Agregar "harnesses": ["memoria"] a un agente experto en
config.json no tenia NINGUN efecto en ese camino: la memoria semantica
(Hermes) nunca llegaba al prompt real de un analisis batch.

Criterio de exito: un agente con harnesses=["memoria"] configurado, al
correr realizar_tarea(), recupera un recuerdo relacionado sembrado en
auditoria_ia y ese recuerdo aparece LITERALMENTE en el prompt real enviado
al modelo. Un agente sin harnesses configurados (default, ej. los agentes
Modbus) no dispara ninguna consulta.

Usa una base SQLite temporal — no toca la DB real del usuario.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.database as db
from core.orchestrator import AgentBase
from core.services import audit_service


class TestMemoriaEnRealizarTarea(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "harness_batch_test.db")
        # agente_id = self.nombre (nombre visible), NO el id de config.json:
        # _contexto_harnesses() usa agente_id_clave or self.nombre como clave
        # de particion (mismo criterio que chat_libre/con_herramientas, que
        # tampoco tienen acceso al id de config.json dentro de AgentBase).
        audit_service.registrar_interaccion(
            tipo="tarea", agente_id="Contador ICI",
            prompt="Analiza telemetria: temperatura Unidad 1 fuera de rango, 95.0 C",
            respuesta="Alerta previa: temperatura Unidad 1 critica, revisar sensor.",
            user_id="operador_local",
        )

    _CFG_BASE = {
        "id": "agente_contabilidad_01", "nombre": "Contador ICI", "tipo_ia": "analitico",
        "area": "Finanzas", "modelo": "mock:agentdesk-demo", "temperatura": 0.0,
        "idioma": "espanol", "prompt_base": "Eres un contador.",
        "siguiente_agente_id": None,
    }

    async def test_01_agente_con_harness_memoria_recibe_recuerdo_en_el_prompt(self):
        cfg = dict(self._CFG_BASE, harnesses=["memoria"])
        agente = AgentBase(cfg, None, "models/gemini-2.5-flash")

        prompt_capturado = {}

        async def _generar_falso(prompt, temperatura=0.4, prioridad=2, modelo_preferido=None):
            prompt_capturado["texto"] = prompt
            return {"texto": ('{"resumen":"ok","kpis":{"Temperatura":"96.0"},'
                              '"tabla":[["Variable","Valor"],["temperatura","96.0"]],'
                              '"evidencia":{"Temperatura":"telemetria.U1.temperatura=96.0"}}'),
                    "proveedor": "mock", "modelo": "mock:agentdesk-demo",
                    "intentos": ["mock:ok"], "degradado": True,
                    "tokens_entrada": 1, "tokens_salida": 1, "tokens_total": 2,
                    "tokens_exactos": False}

        with patch("core.services.llm_service.llm_service.generar", side_effect=_generar_falso):
            resultado = await agente.realizar_tarea(
                "reporte_ventas",
                _datos_override={"telemetria_industrial": {
                    "Agente Telemetria Modbus U1": {"temperatura": {"valor": 96.0}}}},
            )

        self.assertIsNotNone(resultado)
        self.assertIn("temperatura Unidad 1 critica", prompt_capturado.get("texto", ""),
                      "el recuerdo sembrado en auditoria_ia debe llegar al prompt real")

    async def test_02_agente_sin_harnesses_no_consulta_memoria(self):
        cfg = dict(self._CFG_BASE, id="agente_modbus_01", nombre="Agente Telemetria Modbus U1")
        agente = AgentBase(cfg, None, "models/gemini-2.5-flash")
        self.assertEqual(agente.harnesses, [])

        with patch("core.services.harness_service.harness_service.aplicar_pre") as m_pre:
            async def _generar_falso(prompt, temperatura=0.4, prioridad=2, modelo_preferido=None):
                return {"texto": ('{"resumen":"ok","kpis":{"Temperatura":"96.0"},'
                              '"tabla":[["Variable","Valor"],["temperatura","96.0"]],'
                              '"evidencia":{"Temperatura":"telemetria.U1.temperatura=96.0"}}'),
                        "proveedor": "mock", "modelo": "mock:agentdesk-demo",
                        "intentos": ["mock:ok"], "degradado": True,
                        "tokens_entrada": 1, "tokens_salida": 1, "tokens_total": 2,
                        "tokens_exactos": False}
            with patch("core.services.llm_service.llm_service.generar", side_effect=_generar_falso):
                await agente.realizar_tarea("reporte_ventas", _datos_override={"x": 1})

        m_pre.assert_not_called()


if __name__ == "__main__":
    unittest.main()
