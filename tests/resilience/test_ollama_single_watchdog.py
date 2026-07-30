# -*- coding: utf-8 -*-
"""
tests/resilience/test_ollama_single_watchdog.py — Soberania Operativa v1.3-GOLD
(2026-07-30).

Garantia: en Modo Faena (Ollama, CPU) el ExecutionTimeout externo de 650s
(timeout_tarea_s, engine.py) debe ser el UNICO watchdog. El bucle de
auto-correccion de realizar_tarea NO debe lanzar un 2do intento con Ollama,
porque cada llamada puede tardar hasta 600s (LATENCIA_MAX_POR_PROVEEDOR) y
2×600s desbordarian el watchdog de 650s (regresion real: "Gestor Logistico
descartado por timeout a mitad del intento 2").

Criterio:
  - Proveedor "ollama" + 1er reporte invalido  -> generar() se llama UNA vez
    (sin reintento) y realizar_tarea devuelve None. 650s manda solo.
  - Proveedor cloud ("groq") + 1er reporte invalido, 2do valido -> generar()
    se llama DOS veces (auto-correccion intacta para proveedores rapidos).

Usa una DB SQLite temporal — no toca la del usuario.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.database as db
from core.orchestrator import AgentBase

_INVALIDO = ('{"resumen":"x","kpis":{},'          # kpis vacio -> ValidationError
             '"tabla":[["V","Val"]],"evidencia":{"a":"b"}}')
_VALIDO = ('{"resumen":"ok","kpis":{"Temp":"96.0"},'
           '"tabla":[["Variable","Valor"],["temperatura","96.0"]],'
           '"evidencia":{"Temp":"telemetria.U1.temperatura=96.0"}}')

_CFG = {
    "id": "agente_scm_01", "nombre": "Supply Chain Manager", "tipo_ia": "analitico",
    "area": "Supply Chain", "modelo": "ollama:llama3.2", "temperatura": 0.0,
    "idioma": "espanol", "prompt_base": "Eres un experto en cadena de suministro.",
    "siguiente_agente_id": None,   # sin harnesses: cero llamadas LLM extra
}


def _respuesta(texto, proveedor):
    return {"texto": texto, "proveedor": proveedor, "modelo": f"{proveedor}:x",
            "intentos": [f"{proveedor}:ok"], "degradado": False,
            "tokens_entrada": 1, "tokens_salida": 1, "tokens_total": 2,
            "tokens_exactos": False}


class TestOllamaSingleWatchdog(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "watchdog_test.db")

    async def test_01_ollama_no_reintenta(self):
        """Ollama: 1er reporte invalido -> UNA sola llamada, sin 2do intento."""
        agente = AgentBase(dict(_CFG), None, "ollama:llama3.2")
        llamadas = {"n": 0}

        async def _gen(prompt, temperatura=0.4, prioridad=2, modelo_preferido=None):
            llamadas["n"] += 1
            return _respuesta(_INVALIDO, "ollama")   # siempre invalido

        with patch("core.services.llm_service.llm_service.generar", side_effect=_gen):
            resultado = await agente.realizar_tarea(
                "reporte_ventas",
                _datos_override={"telemetria_industrial": {"U1": {"temperatura": 96.0}}},
            )

        self.assertEqual(llamadas["n"], 1,
                         "Ollama NO debe reintentar: 650s es el unico watchdog")
        self.assertIsNone(resultado, "reporte invalido tras la unica pasada -> None")

    async def test_02_cloud_conserva_autocorreccion(self):
        """Cloud (groq): 1er invalido, 2do valido -> DOS llamadas, reporte OK."""
        agente = AgentBase(dict(_CFG, id="agente_finanzas_corp_01",
                                nombre="Analista Finanzas Corporativas",
                                modelo="groq:llama-3.1"), None, "groq:llama-3.1")
        secuencia = [(_INVALIDO, "groq"), (_VALIDO, "groq")]
        llamadas = {"n": 0}

        async def _gen(prompt, temperatura=0.4, prioridad=2, modelo_preferido=None):
            texto, prov = secuencia[min(llamadas["n"], len(secuencia) - 1)]
            llamadas["n"] += 1
            return _respuesta(texto, prov)

        with patch("core.services.llm_service.llm_service.generar", side_effect=_gen):
            resultado = await agente.realizar_tarea(
                "reporte_ventas", _datos_override={"x": 1})

        self.assertEqual(llamadas["n"], 2,
                         "los proveedores cloud rapidos conservan la auto-correccion")
        self.assertIsNotNone(resultado, "el 2do intento valido debe producir reporte")


if __name__ == "__main__":
    unittest.main()
