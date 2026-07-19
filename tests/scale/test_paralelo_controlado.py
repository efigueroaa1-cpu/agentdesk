# -*- coding: utf-8 -*-
"""
tests/scale/test_paralelo_controlado.py — Soberanía Operativa masiva (2026-07-19).

Criterio: la ejecución "todos en paralelo" respeta max_agentes_paralelo y
timeout_tarea_s del bloque orquestador de config.json (antes eran metadata
inerte: el gather de main.py lanzaba los 22 agentes de golpe → ráfaga →
RateLimit/latencia → breakers abiertos → respuestas mock → GroundingGuard
abortando "alucinaciones" que eran del mock), y los agentes expertos reciben
la telemetría consolidada como raw_data (antes: datos_trabajo.json vacío).

Correr:  python -m unittest tests.scale.test_paralelo_controlado -v
"""
import asyncio
import json
import unittest
from unittest.mock import patch

from core.orchestrator import AgentBase, Orquestador


class _AgenteFake:
    """Doble de AgentBase: registra concurrencia y datos recibidos."""

    contador = 0
    pico = 0

    def __init__(self, nombre, tardanza_s=0.05):
        self.nombre = nombre
        self._tardanza = tardanza_s
        self.datos_recibidos = None

    async def realizar_tarea(self, tarea, _datos_override=None):
        self.datos_recibidos = _datos_override
        _AgenteFake.contador += 1
        _AgenteFake.pico = max(_AgenteFake.pico, _AgenteFake.contador)
        try:
            await asyncio.sleep(self._tardanza)
        finally:
            _AgenteFake.contador -= 1
        return {"resumen": f"ok-{self.nombre}"}


def _orquestador_con(agentes: dict, cfg_orq: dict) -> Orquestador:
    orq = object.__new__(Orquestador)   # sin __init__: solo agentes+config
    orq.agentes = agentes
    orq.config = {"orquestador": cfg_orq, "agents": []}
    return orq


class TestParaleloControlado(unittest.TestCase):

    def setUp(self):
        _AgenteFake.contador = 0
        _AgenteFake.pico = 0

    def test_01_respeta_max_agentes_paralelo(self):
        agentes = {f"a{i}": _AgenteFake(f"A{i}") for i in range(10)}
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 4,
                                         "timeout_tarea_s": 5})
        resultados = asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))
        self.assertEqual(len(resultados), 10)
        self.assertTrue(all(r is not None for r in resultados))
        self.assertLessEqual(_AgenteFake.pico, 4,
                             "la rafaga supero max_agentes_paralelo")

    def test_02_timeout_tarea_devuelve_none_sin_romper_al_resto(self):
        agentes = {"lento": _AgenteFake("Lento", tardanza_s=5.0),
                   "sano": _AgenteFake("Sano", tardanza_s=0.01)}
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 4,
                                         "timeout_tarea_s": 0.2})
        resultados = asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))
        self.assertIsNone(resultados[0], "el agente colgado debe dar None por timeout")
        self.assertIsNotNone(resultados[1], "el timeout de uno no puede matar al resto")

    def test_03_datos_override_llega_a_todos_los_agentes(self):
        snapshot = {"telemetria_industrial": {"U1": {"temperatura": {"valor": 21.5}}}}
        agentes = {f"a{i}": _AgenteFake(f"A{i}", tardanza_s=0.0) for i in range(3)}
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 4,
                                         "timeout_tarea_s": 5})
        asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas",
                                                datos_override=snapshot))
        for ag in agentes.values():
            self.assertEqual(ag.datos_recibidos, snapshot)

    def test_04_defaults_sin_bloque_orquestador(self):
        """Sin bloque orquestador en config: defaults 4 y 180, jamás lanza."""
        agentes = {"a": _AgenteFake("A", tardanza_s=0.0)}
        orq = object.__new__(Orquestador)
        orq.agentes = agentes
        orq.config = {"agents": []}
        resultados = asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))
        self.assertEqual(len(resultados), 1)


class TestDistribucionDatos(unittest.TestCase):
    """realizar_tarea con _datos_override dict + log DATOS_ENTRADA."""

    _CFG = {
        "id": "agente_test_dd", "nombre": "Experto Test", "tipo_ia": "analitico",
        "area": "Test", "modelo": "mock:agentdesk-demo", "temperatura": 0.0,
        "idioma": "espanol", "prompt_base": "Eres un analista.",
        "siguiente_agente_id": None,
    }

    _RESPUESTA_OK = json.dumps({
        "resumen": "Telemetria U1 en rango.",
        "kpis": {"Temperatura U1": "21.5"},
        "tabla": [["Variable", "Valor"], ["temperatura", "21.5"]],
        "evidencia": {"Temperatura U1": "telemetria_industrial.U1.temperatura.valor = 21.5"},
    })

    def test_05_override_dict_se_usa_como_raw_data_y_se_loguea(self):
        snapshot = {"telemetria_industrial": {
            "U1": {"temperatura": {"valor": 21.5, "unidad": "C", "registro": 40001}}}}
        agente = AgentBase(dict(self._CFG), None, "models/gemini-2.5-flash")

        async def _generar_falso(prompt, temperatura=0.4, prioridad=2,
                                 modelo_preferido=None):
            # El prompt del experto debe contener la telemetria consolidada
            assert "21.5" in prompt and "telemetria_industrial" in prompt
            return {"texto": self._RESPUESTA_OK, "proveedor": "mock",
                    "modelo": "mock:agentdesk-demo", "intentos": ["mock:ok"],
                    "degradado": True, "tokens_entrada": 1, "tokens_salida": 1,
                    "tokens_total": 2, "tokens_exactos": False}

        with patch("core.services.llm_service.llm_service.generar",
                   side_effect=_generar_falso):
            with self.assertLogs("core.orchestrator", level="INFO") as capturado:
                resultado = asyncio.run(
                    agente.realizar_tarea("reporte_ventas",
                                          _datos_override=snapshot))

        self.assertIsNotNone(resultado, "con datos reales y cita exacta debe pasar")
        lineas_datos = [l for l in capturado.output if "DATOS_ENTRADA" in l]
        self.assertTrue(lineas_datos, "falta el log DATOS_ENTRADA del experto")
        self.assertIn("21.5", lineas_datos[0],
                      "el log debe mostrar el contenido exacto de la entrada")
        self.assertIn("Experto Test", lineas_datos[0])

    def test_06_schema_invalido_final_queda_logueado_con_campos(self):
        """El 3er intento con schema invalido debe dejar ERROR con los campos
        que fallaron — antes devolvia None en silencio y el 'reporte invalido'
        de U1-U5 fue indiagnosticable desde sistema.log."""
        respuesta_mala = json.dumps({
            "resumen": "ok", "kpis": {"t": "1"},
            "tabla": [["Variable", "Valor"], ["temperatura", 20.0]],  # celda float
            "evidencia": {"t": "x"},
        })
        agente = AgentBase(dict(self._CFG), None, "models/gemini-2.5-flash")

        async def _generar_malo(prompt, temperatura=0.4, prioridad=2,
                                modelo_preferido=None):
            return {"texto": respuesta_mala, "proveedor": "mock",
                    "modelo": "mock:agentdesk-demo", "intentos": ["mock:ok"],
                    "degradado": True, "tokens_entrada": 1, "tokens_salida": 1,
                    "tokens_total": 2, "tokens_exactos": False}

        with patch("core.services.llm_service.llm_service.generar",
                   side_effect=_generar_malo):
            with self.assertLogs("core.orchestrator", level="ERROR") as capturado:
                resultado = asyncio.run(agente.realizar_tarea("reporte_ventas"))

        self.assertIsNone(resultado)
        finales = [l for l in capturado.output if "schema" in l.lower()]
        self.assertTrue(finales, "falta el ERROR final de schema invalido")
        self.assertIn("tabla", finales[0],
                      "el log debe nombrar el campo que fallo")


if __name__ == "__main__":
    unittest.main()
