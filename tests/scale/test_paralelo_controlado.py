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
from unittest.mock import AsyncMock, patch

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


class _AgenteFakeOrden:
    """Doble de AgentBase: registra el orden real de DESPACHO (cuando se
    invoca realizar_tarea), no solo el resultado."""

    llamadas_orden: list[str] = []

    def __init__(self, aid, tardanza_s=0.0):
        self.aid = aid
        self.nombre = aid
        self._tardanza = tardanza_s

    async def realizar_tarea(self, tarea, _datos_override=None):
        _AgenteFakeOrden.llamadas_orden.append(self.aid)
        if self._tardanza:
            await asyncio.sleep(self._tardanza)
        return {"resumen": f"ok-{self.aid}"}


class TestOrdenDeDespachoPrioritario(unittest.TestCase):
    """agentes_prioritarios (2026-07-20): con cuota diaria casi agotada solo
    alcanza para las primeras llamadas del lote -- lo unico que puede
    cambiar eso es QUIEN sale primero, no delays artificiales (que no
    liberan cuota diaria/TPD)."""

    def setUp(self):
        _AgenteFakeOrden.llamadas_orden = []

    def test_11_agentes_prioritarios_se_despachan_primero(self):
        agentes = {aid: _AgenteFakeOrden(aid) for aid in ["a1", "a2", "a3", "a4", "a5"]}
        orq = _orquestador_con(agentes, {
            "max_agentes_paralelo": 1,   # serializa -> orden 100% determinista
            "timeout_tarea_s": 5,
            "agentes_prioritarios": ["a4", "a2"],
        })
        asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))

        self.assertEqual(_AgenteFakeOrden.llamadas_orden[:2], ["a4", "a2"],
                         "los prioritarios deben despacharse primero, en su orden declarado")
        self.assertEqual(set(_AgenteFakeOrden.llamadas_orden), set(agentes.keys()))

    def test_12_orden_de_retorno_no_cambia_pese_a_la_prioridad(self):
        agentes = {aid: _AgenteFakeOrden(aid) for aid in ["a1", "a2", "a3"]}
        orq = _orquestador_con(agentes, {
            "max_agentes_paralelo": 1, "timeout_tarea_s": 5,
            "agentes_prioritarios": ["a3"],
        })
        resultados = asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))
        self.assertEqual([r["resumen"] for r in resultados], ["ok-a1", "ok-a2", "ok-a3"],
                         "el orden de RETORNO sigue siendo el de config.json")

    def test_13_sin_prioritarios_el_despacho_es_el_orden_original(self):
        agentes = {aid: _AgenteFakeOrden(aid) for aid in ["a1", "a2", "a3"]}
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 1, "timeout_tarea_s": 5})
        asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))
        self.assertEqual(_AgenteFakeOrden.llamadas_orden, ["a1", "a2", "a3"])

    def test_14_id_prioritario_inexistente_se_ignora_sin_romper(self):
        agentes = {aid: _AgenteFakeOrden(aid) for aid in ["a1", "a2"]}
        orq = _orquestador_con(agentes, {
            "max_agentes_paralelo": 1, "timeout_tarea_s": 5,
            "agentes_prioritarios": ["fantasma", "a2"],
        })
        resultados = asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))
        self.assertEqual(_AgenteFakeOrden.llamadas_orden, ["a2", "a1"])
        self.assertEqual(len(resultados), 2)


class _AgenteFakeConProveedor:
    """Doble de AgentBase: simula que llm_service degrado (o no) fuera de Groq.

    modelo=preferido del agente (config.json); proveedor_real=lo que
    realmente respondio (canal lateral ultimo_proveedor_llm, ADR-0019).
    """

    def __init__(self, nombre, modelo, proveedor_real):
        self.nombre = nombre
        self.modelo = modelo
        self.ultimo_proveedor_llm = ""
        self._proveedor_real = proveedor_real

    async def realizar_tarea(self, tarea, _datos_override=None):
        self.ultimo_proveedor_llm = self._proveedor_real
        return {"resumen": f"ok-{self.nombre}"}


class TestJitterSaturacionGroq(unittest.TestCase):
    """429 persistente en Groq -> espaciar la rafaga con jitter (2026-07-20)."""

    def test_07_dos_degradaciones_seguidas_activan_jitter_antes_del_3ro(self):
        agentes = {
            "a1": _AgenteFakeConProveedor("A1", "groq:llama-3.3-70b-versatile", "mock"),
            "a2": _AgenteFakeConProveedor("A2", "groq:llama-3.3-70b-versatile", "mock"),
            "a3": _AgenteFakeConProveedor("A3", "groq:llama-3.3-70b-versatile", "mock"),
        }
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 1, "timeout_tarea_s": 5})

        with patch("core.orchestrator.asyncio.sleep", new_callable=AsyncMock) as m_sleep:
            asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))

        esperas = [c.args[0] for c in m_sleep.call_args_list]
        self.assertTrue(esperas, "no se aplico jitter tras 2 degradaciones seguidas de Groq")
        self.assertGreaterEqual(esperas[0], 1.5, "el jitter debe ser >= 1.5s")

    def test_08_exito_real_en_groq_resetea_el_contador(self):
        agentes = {
            "a1": _AgenteFakeConProveedor("A1", "groq:llama-3.3-70b-versatile", "mock"),
            "a2": _AgenteFakeConProveedor("A2", "groq:llama-3.3-70b-versatile", "mock"),
            "a3": _AgenteFakeConProveedor("A3", "groq:llama-3.3-70b-versatile", "groq"),
            "a4": _AgenteFakeConProveedor("A4", "groq:llama-3.3-70b-versatile", "mock"),
        }
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 1, "timeout_tarea_s": 5})

        with patch("core.orchestrator.asyncio.sleep", new_callable=AsyncMock) as m_sleep:
            asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))

        # a1+a2 degradan (jitter antes de a3); a3 responde con Groq real ->
        # resetea; a4 degrada solo (1, bajo el umbral) -> sin jitter nuevo.
        self.assertEqual(len(m_sleep.call_args_list), 1)

    def test_09_agentes_no_groq_nunca_activan_jitter(self):
        agentes = {
            "a1": _AgenteFakeConProveedor("A1", "gemini:models/gemini-2.5-flash", "mock"),
            "a2": _AgenteFakeConProveedor("A2", "gemini:models/gemini-2.5-flash", "mock"),
            "a3": _AgenteFakeConProveedor("A3", "gemini:models/gemini-2.5-flash", "mock"),
        }
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 1, "timeout_tarea_s": 5})

        with patch("core.orchestrator.asyncio.sleep", new_callable=AsyncMock) as m_sleep:
            asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))

        m_sleep.assert_not_called()

    def test_10_una_sola_degradacion_no_alcanza_el_umbral(self):
        agentes = {
            "a1": _AgenteFakeConProveedor("A1", "groq:llama-3.3-70b-versatile", "mock"),
            "a2": _AgenteFakeConProveedor("A2", "groq:llama-3.3-70b-versatile", "groq"),
        }
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 1, "timeout_tarea_s": 5})

        with patch("core.orchestrator.asyncio.sleep", new_callable=AsyncMock) as m_sleep:
            asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))

        m_sleep.assert_not_called()


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

    def test_07_ollama_se_capa_a_2_intentos_no_3(self):
        """Hallazgo real (2026-07-20, corrida en vivo): con Ollama como
        proveedor real (hasta 300s por llamada), 3 intentos completos podian
        exceder timeout_tarea_s externo antes de que el 2do/3er intento
        siquiera terminara -- 'Gestor Logistico' quedo descartado por
        timeout a mitad del intento 2. Con Ollama, el bucle debe rendirse
        en 2 intentos (no 3) para dejarle margen real al timeout externo."""
        llamadas = {"n": 0}

        async def _generar_ollama_json_invalido(prompt, temperatura=0.4,
                                                 prioridad=2, modelo_preferido=None):
            llamadas["n"] += 1
            return {"texto": "esto no es JSON valido en absoluto",
                    "proveedor": "ollama", "modelo": "ollama:llama3.2",
                    "intentos": ["ollama:ok"], "degradado": False,
                    "tokens_entrada": 1, "tokens_salida": 1, "tokens_total": 2,
                    "tokens_exactos": False}

        agente = AgentBase(dict(self._CFG), None, "models/gemini-2.5-flash")
        with patch("core.services.llm_service.llm_service.generar",
                   side_effect=_generar_ollama_json_invalido):
            with self.assertLogs("core.orchestrator", level="ERROR") as capturado:
                resultado = asyncio.run(agente.realizar_tarea("reporte_ventas"))

        self.assertIsNone(resultado)
        self.assertEqual(llamadas["n"], 2,
                         "con Ollama respondiendo, debe rendirse tras 2 intentos, no 3")
        finales = [l for l in capturado.output if "JSON" in l or "json" in l.lower()]
        self.assertTrue(any("2 intentos" in l for l in finales),
                        "el log final debe reflejar el limite REAL usado (2), no 3")

    def test_08_proveedor_rapido_conserva_los_3_intentos(self):
        """Regresion: proveedores rapidos (groq/gemini/mock) NO deben verse
        afectados por el limite reducido de Ollama."""
        llamadas = {"n": 0}

        async def _generar_groq_json_invalido(prompt, temperatura=0.4,
                                              prioridad=2, modelo_preferido=None):
            llamadas["n"] += 1
            return {"texto": "no es JSON", "proveedor": "groq",
                    "modelo": "groq:llama-3.3-70b-versatile", "intentos": ["groq:ok"],
                    "degradado": False, "tokens_entrada": 1, "tokens_salida": 1,
                    "tokens_total": 2, "tokens_exactos": False}

        agente = AgentBase(dict(self._CFG), None, "models/gemini-2.5-flash")
        with patch("core.services.llm_service.llm_service.generar",
                   side_effect=_generar_groq_json_invalido):
            asyncio.run(agente.realizar_tarea("reporte_ventas"))

        self.assertEqual(llamadas["n"], 3,
                         "groq (rapido) debe conservar los 3 intentos de siempre")


class _AgenteFakeAuditado:
    """Doble de AgentBase con los canales laterales que _auditar_batch lee
    (modelo, ultimo_proveedor_llm, ultimo_tokens_llm) -- espejo de
    _AgenteFakeConProveedor pero para la suite de auditoria."""

    def __init__(self, nombre, resultado=None, tardanza_s=0.0, revienta=False):
        self.nombre = nombre
        self.modelo = "groq:llama-3.3-70b-versatile"
        self.ultimo_proveedor_llm = "groq"
        self.ultimo_tokens_llm = {"tokens_total": 42, "tokens_exactos": True}
        self._resultado = resultado if resultado is not None else {"resumen": f"ok-{nombre}"}
        self._tardanza = tardanza_s
        self._revienta = revienta

    async def realizar_tarea(self, tarea, _datos_override=None):
        if self._tardanza:
            await asyncio.sleep(self._tardanza)
        if self._revienta:
            raise RuntimeError("proveedor cayo a mitad de la tarea")
        return self._resultado


class TestAuditoriaBatch(unittest.TestCase):
    """Opcion 23 (ejecutar_todos_paralelo) debe dejar rastro forense en
    auditoria_ia igual que el chat y la ejecucion individual via HTTP
    (orchestrator_service._auditar) -- hallazgo real: realizar_tarea() en
    el lote NUNCA llamaba a audit_service, asi que las 22 ejecuciones del
    batch eran invisibles para el Panel de Auditoria."""

    def test_15_cada_agente_exitoso_deja_una_traza_tarea_batch(self):
        agentes = {aid: _AgenteFakeAuditado(aid) for aid in ["a1", "a2", "a3"]}
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 4, "timeout_tarea_s": 5})

        with patch("core.services.audit_service.registrar_interaccion") as m_aud:
            resultados = asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))

        self.assertEqual(len(resultados), 3)
        self.assertEqual(m_aud.call_count, 3)
        ids_auditados = {c.kwargs["agente_id"] for c in m_aud.call_args_list}
        self.assertEqual(ids_auditados, {"a1", "a2", "a3"})
        for c in m_aud.call_args_list:
            self.assertEqual(c.kwargs["tipo"], "tarea_batch")
            self.assertTrue(c.kwargs["exitoso"])
            self.assertEqual(c.kwargs["proveedor"], "groq")

    def test_16_timeout_se_audita_como_fallo_no_se_omite(self):
        agentes = {
            "lento": _AgenteFakeAuditado("lento", tardanza_s=5.0),
            "sano":  _AgenteFakeAuditado("sano", tardanza_s=0.0),
        }
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 4, "timeout_tarea_s": 0.2})

        with patch("core.services.audit_service.registrar_interaccion") as m_aud:
            asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))

        self.assertEqual(m_aud.call_count, 2, "el timeout tambien debe dejar rastro")
        por_id = {c.kwargs["agente_id"]: c.kwargs for c in m_aud.call_args_list}
        self.assertFalse(por_id["lento"]["exitoso"])
        self.assertIn("timeout", por_id["lento"]["veredicto_guardrail"])
        self.assertTrue(por_id["sano"]["exitoso"])

    def test_17_auditoria_es_best_effort_no_rompe_el_lote(self):
        """Si audit_service falla (ej. SQLite ocupado), el resultado de
        negocio del agente debe sobrevivir igual -- mismo criterio que
        orchestrator_service._auditar ('traza forense best-effort')."""
        agentes = {"a1": _AgenteFakeAuditado("a1")}
        orq = _orquestador_con(agentes, {"max_agentes_paralelo": 4, "timeout_tarea_s": 5})

        with patch("core.services.audit_service.registrar_interaccion",
                   side_effect=RuntimeError("DB ocupada")):
            resultados = asyncio.run(orq.ejecutar_todos_paralelo("reporte_ventas"))

        self.assertEqual(resultados, [{"resumen": "ok-a1"}])


if __name__ == "__main__":
    unittest.main()
