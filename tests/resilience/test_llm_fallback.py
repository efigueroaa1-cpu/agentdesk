# -*- coding: utf-8 -*-
"""
tests/resilience/test_llm_fallback.py — Resiliencia de Inteligencia (Fase 8).

Criterio de éxito de la fase: una tarea de reporte se completa aunque el
proveedor de IA principal falle a mitad del proceso.

Correr:  python -m unittest tests.resilience.test_llm_fallback -v
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from core.services.llm_service import LlmService


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=30))


def _generador_con_fallos(fallan: set[str], colgados: set[str] | None = None):
    """Doble de providers.generate: proveedores marcados fallan o se cuelgan."""
    colgados = colgados or set()
    llamadas: list[str] = []

    async def generar(model_id, prompt, temperatura=0.4, prioridad=2):
        proveedor = model_id.split(":", 1)[0]
        llamadas.append(proveedor)
        if proveedor in colgados:
            await asyncio.sleep(3600)
        if proveedor in fallan:
            raise ConnectionError(f"HTTP 503 en {proveedor}")
        return f"respuesta-de-{proveedor}"

    generar.llamadas = llamadas
    return generar


class TestLlmFallback(unittest.TestCase):

    def test_01_proveedor_sano_responde_directo(self):
        gen = _generador_con_fallos(fallan=set())
        r = _run(LlmService(generador=gen).generar("informe de ventas"))
        self.assertEqual(r["proveedor"], "groq")
        self.assertFalse(r["degradado"])

    def test_02_fallo_del_principal_salta_al_siguiente(self):
        """Groq cae con 5xx a mitad del proceso → Gemini completa la tarea."""
        gen = _generador_con_fallos(fallan={"groq"})
        r = _run(LlmService(generador=gen).generar("informe de ventas"))
        self.assertEqual(r["proveedor"], "gemini")
        self.assertIn("groq:ConnectionError", r["intentos"])

    def test_03_cadena_completa_degrada_a_mock(self):
        """Los 4 proveedores reales (incl. Ollama local) caídos → el mock SIEMPRE responde."""
        gen = _generador_con_fallos(fallan={"groq", "gemini", "openai", "ollama"})
        r = _run(LlmService(generador=gen).generar("informe de ventas"))
        self.assertEqual(r["proveedor"], "mock")
        self.assertTrue(r["degradado"])
        self.assertTrue(r["texto"].startswith("respuesta-de-mock"))

    def test_04_latencia_excesiva_abre_el_circuito(self):
        """Un proveedor colgado (>latencia máx.) se salta por timeout."""
        gen = _generador_con_fallos(fallan=set(), colgados={"groq"})
        svc = LlmService(generador=gen, latencia_max_s=0.2)
        r = _run(svc.generar("informe"))
        self.assertEqual(r["proveedor"], "gemini")
        self.assertTrue(any("latencia" in i for i in r["intentos"]))

    def test_05_circuit_breaker_marca_inactivo_y_no_reintenta(self):
        """Tras N fallos consecutivos el circuito abre: ni una llamada más."""
        gen = _generador_con_fallos(fallan={"groq"})
        svc = LlmService(generador=gen)

        _run(svc.generar("a"))   # fallo 1 de groq
        _run(svc.generar("b"))   # fallo 2 → circuito abierto
        llamadas_previas = gen.llamadas.count("groq")

        r = _run(svc.generar("c"))
        self.assertEqual(gen.llamadas.count("groq"), llamadas_previas,
                         "Con el circuito abierto no debe llamarse a groq")
        self.assertIn("groq:circuito-abierto", r["intentos"])
        self.assertFalse(svc.estado_circuitos()["groq"]["activo"])

    def test_06_circuito_se_recupera_tras_enfriamiento(self):
        """Semi-abierto: pasado el enfriamiento se permite reintentar y sanar."""
        gen = _generador_con_fallos(fallan={"groq"})
        svc = LlmService(generador=gen)
        _run(svc.generar("a")); _run(svc.generar("b"))
        self.assertFalse(svc.estado_circuitos()["groq"]["activo"])

        svc._circuitos["groq"].abierto_hasta = 0.0   # simular fin de enfriamiento
        gen2 = _generador_con_fallos(fallan=set())

        async def _gen2_con_uso(model_id, prompt, temperatura=0.4, prioridad=2):
            texto = await gen2(model_id, prompt, temperatura, prioridad)
            return {"texto": texto, "tokens_entrada": 1, "tokens_salida": 1,
                    "tokens_total": 2, "tokens_exactos": False}

        svc._generar_con_uso = _gen2_con_uso          # groq "se recuperó"
        r = _run(svc.generar("c"))
        self.assertEqual(r["proveedor"], "groq")
        self.assertTrue(svc.estado_circuitos()["groq"]["activo"])

    def test_07_reset_forzado_cierra_el_circuito_sin_esperar(self):
        """resetear_circuito('gemini') cierra el circuito YA: siguiente llamada
        vuelve a intentar el proveedor sin esperar el enfriamiento (caso real:
        se corrigió la API key y no queremos esperar 120s)."""
        gen = _generador_con_fallos(fallan={"groq", "gemini"})
        svc = LlmService(generador=gen)
        _run(svc.generar("a")); _run(svc.generar("b"))   # abre groq y gemini
        self.assertFalse(svc.estado_circuitos()["gemini"]["activo"])

        svc.resetear_circuito("gemini")

        estado = svc.estado_circuitos()["gemini"]
        self.assertTrue(estado["activo"])
        self.assertEqual(estado["fallos_consecutivos"], 0)
        self.assertEqual(estado["ultimo_error"], "")
        # groq NO fue tocado: su circuito sigue abierto
        self.assertFalse(svc.estado_circuitos()["groq"]["activo"])

        gen2 = _generador_con_fallos(fallan=set())
        llamadas_gemini_previas = gen.llamadas.count("gemini")

        async def _gen2_con_uso(model_id, prompt, temperatura=0.4, prioridad=2):
            texto = await gen2(model_id, prompt, temperatura, prioridad)
            return {"texto": texto, "tokens_entrada": 1, "tokens_salida": 1,
                    "tokens_total": 2, "tokens_exactos": False}

        svc._generar_con_uso = _gen2_con_uso              # "la clave nueva funciona"
        r = _run(svc.generar("c"))
        self.assertEqual(r["proveedor"], "gemini")
        self.assertEqual(gen.llamadas.count("gemini"), llamadas_gemini_previas,
                         "gemini debe reintentarse via el generador nuevo, no el viejo")

    def test_08_reset_sin_proveedor_cierra_todos(self):
        """resetear_circuito() sin argumento resetea TODOS los circuitos."""
        gen = _generador_con_fallos(fallan={"groq", "gemini", "openai", "ollama"})
        svc = LlmService(generador=gen)
        _run(svc.generar("a")); _run(svc.generar("b"))
        abiertos = [p for p, e in svc.estado_circuitos().items() if not e["activo"]]
        self.assertGreaterEqual(len(abiertos), 2)

        reseteados = svc.resetear_circuito()

        self.assertEqual(sorted(reseteados), sorted(abiertos),
                         "debe informar exactamente los circuitos que estaban abiertos")
        for p, e in svc.estado_circuitos().items():
            self.assertTrue(e["activo"], f"{p} debia quedar cerrado tras el reset")
            self.assertEqual(e["fallos_consecutivos"], 0)

    def test_09_reset_de_proveedor_desconocido_no_rompe(self):
        """Un proveedor inexistente devuelve lista vacia, jamas lanza."""
        svc = LlmService(generador=_generador_con_fallos(fallan=set()))
        self.assertEqual(svc.resetear_circuito("anthropic"), [])


def _generador_con_error(mensajes: dict[str, list[str]]):
    """Doble: por cada proveedor, una lista de mensajes de error a lanzar en
    orden (uno por llamada); agotada la lista, responde ok. Permite simular
    "falla N veces con este 429 especifico y despues sana" para probar el
    reintento inteligente por ventana de cuota."""
    restantes = {p: list(m) for p, m in mensajes.items()}
    llamadas: list[str] = []

    async def generar(model_id, prompt, temperatura=0.4, prioridad=2):
        proveedor = model_id.split(":", 1)[0]
        llamadas.append(proveedor)
        cola = restantes.get(proveedor, [])
        if cola:
            raise RuntimeError(cola.pop(0))
        return f"respuesta-de-{proveedor}"

    generar.llamadas = llamadas
    return generar


class TestReintentoInteligentePorVentanaDeCuota(unittest.TestCase):
    """429 persistente (2026-07-20): distinguir limite POR MINUTO (recuperable
    en segundos, vale un reintento corto) de limite POR DIA (Groq/Gemini TPD,
    reintentar de inmediato es puro desperdicio -- el propio proveedor dice
    "please retry in Nm", no "in Ns")."""

    MSG_TPM_GROQ = ("Rate limit reached for model `llama-3.3-70b-versatile` "
                    "on requests per minute (RPM): Limit 30, Used 30, "
                    "Requested 1. Please try again in 2s.")
    MSG_TPD_GROQ = ("Rate limit reached for model `llama-3.3-70b-versatile` "
                    "on tokens per day (TPD): Limit 100000, Used 99290, "
                    "Requested 1743. Please try again in 14m52s.")
    MSG_TPD_GEMINI = ("Quota exceeded for metric: generate_content_free_tier_requests. "
                      "GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    def test_16_limite_por_minuto_reintenta_y_recupera_sin_caer_al_fallback(self):
        """Un 429 de RPM que se resuelve en el 2do intento NO debe saltar a
        Gemini -- el reintento corto alcanza para que Groq responda igual."""
        gen = _generador_con_error({"groq": [self.MSG_TPM_GROQ]})
        with patch("core.services.llm_service.asyncio.sleep",
                  new_callable=AsyncMock) as m_sleep:
            r = _run(LlmService(generador=gen).generar("informe"))
        self.assertEqual(r["proveedor"], "groq",
                         "el reintento corto debe alcanzar, sin caer a Gemini")
        self.assertEqual(gen.llamadas.count("groq"), 2, "1 fallo + 1 reintento")
        m_sleep.assert_called_once()
        self.assertAlmostEqual(m_sleep.call_args.args[0], 5.0, delta=0.01)

    def test_17_limite_diario_NO_reintenta_salta_directo_al_fallback(self):
        """Un 429 de TPD/RPD no debe esperar ni reintentar -- salta a Gemini
        de inmediato (reintentar solo repetiria el mismo error)."""
        gen = _generador_con_error({"groq": [self.MSG_TPD_GROQ]})
        with patch("core.services.llm_service.asyncio.sleep",
                  new_callable=AsyncMock) as m_sleep:
            r = _run(LlmService(generador=gen).generar("informe"))
        self.assertEqual(r["proveedor"], "gemini")
        self.assertEqual(gen.llamadas.count("groq"), 1,
                         "limite diario: UN solo intento, cero reintentos")
        m_sleep.assert_not_called()

    def test_18_reintentos_topados_en_2_luego_cae_al_fallback(self):
        """Si el limite por minuto persiste mas de REINTENTOS_LIMITE_MINUTO,
        se abandona el proveedor (no reintenta para siempre)."""
        gen = _generador_con_error({"groq": [self.MSG_TPM_GROQ, self.MSG_TPM_GROQ,
                                             self.MSG_TPM_GROQ]})
        with patch("core.services.llm_service.asyncio.sleep",
                  new_callable=AsyncMock):
            r = _run(LlmService(generador=gen).generar("informe"))
        self.assertEqual(r["proveedor"], "gemini")
        self.assertEqual(gen.llamadas.count("groq"), 3,
                         "1 intento inicial + 2 reintentos (tope), despues abandona")

    def test_19_gemini_limite_diario_tampoco_reintenta(self):
        """El mismo criterio aplica a Gemini (RequestsPerDay), no solo Groq."""
        gen = _generador_con_error({"groq": ["boom"], "gemini": [self.MSG_TPD_GEMINI]})
        with patch("core.services.llm_service.asyncio.sleep",
                  new_callable=AsyncMock) as m_sleep:
            _run(LlmService(generador=gen).generar("informe"))
        self.assertEqual(gen.llamadas.count("gemini"), 1)
        m_sleep.assert_not_called()


def _generador_con_demora(demoras: dict[str, float]):
    """Doble: cada proveedor listado duerme la cantidad indicada de segundos
    antes de responder OK; el resto responde de inmediato."""
    async def generar(model_id, prompt, temperatura=0.4, prioridad=2):
        proveedor = model_id.split(":", 1)[0]
        if proveedor in demoras:
            await asyncio.sleep(demoras[proveedor])
        return f"respuesta-de-{proveedor}"
    return generar


class TestLatenciaPorProveedorOllama(unittest.TestCase):
    """Ollama corre en hardware local sin costo/cuota externa -- el limite
    de latencia global (pensado para cortar proveedores CLOUD colgados) era
    demasiado estricto para inferencia local bajo carga concurrente real
    (2026-07-20: 3 agentes ICI concurrentes excedieron 30s y abrieron el
    circuito de Ollama, cayendo los 22 agentes a Mock pese a que Ollama
    respondia)."""

    _CADENA_CORTA = [("groq", "groq:llama-3.3-70b-versatile"),
                     ("ollama", "ollama:llama3.2"),
                     ("mock", "mock:agentdesk-demo")]

    def test_20_ollama_tolera_mas_latencia_que_el_limite_global(self):
        gen = _generador_con_demora({"groq": 10, "ollama": 0.3})
        svc = LlmService(generador=gen, cadena=self._CADENA_CORTA,
                         latencia_max_s=0.1, latencia_por_proveedor={"ollama": 0.5})
        r = _run(svc.generar("informe"))
        self.assertEqual(r["proveedor"], "ollama",
                         "0.3s debe caber en el presupuesto especifico de ollama (0.5s)")

    def test_21_sin_override_ollama_usa_el_mismo_limite_global_que_los_demas(self):
        gen = _generador_con_demora({"groq": 10, "ollama": 0.3})
        svc = LlmService(generador=gen, cadena=self._CADENA_CORTA,
                         latencia_max_s=0.1, latencia_por_proveedor={})
        r = _run(svc.generar("informe"))
        self.assertEqual(r["proveedor"], "mock",
                         "sin override, 0.3s excede el limite global de 0.1s -- cae a mock")

    def test_22_override_de_ollama_no_afecta_a_otros_proveedores(self):
        gen = _generador_con_demora({"groq": 0.3})
        svc = LlmService(generador=gen, latencia_max_s=0.1,
                         latencia_por_proveedor={"ollama": 5.0})
        r = _run(svc.generar("informe"))
        self.assertNotEqual(r["proveedor"], "groq",
                            "groq no tiene override -- sigue respetando el limite global")

    def test_23_default_de_produccion_es_60s_para_ollama(self):
        from core.services.llm_service import LATENCIA_MAX_POR_PROVEEDOR
        self.assertEqual(LATENCIA_MAX_POR_PROVEEDOR.get("ollama"), 60.0)


class TestMockReporteEstructurado(unittest.TestCase):
    """Optimizacion de Mock (2026-07-19): cuando el prompt pide un reporte
    JSON, la respuesta mock debe cumplir ReporteAgente ESTRICTAMENTE y
    sobrevivir el pipeline completo (incluido GroundingGuard) — antes
    devolvia texto plano, el parseo JSON fallaba 3 veces y los 15 expertos
    degradados abortaban al 0% con 'reporte invalido'."""

    PROMPT_JSON = (
        "Eres un analista. Analiza: {'ventas': 1000}. "
        "Responde ÚNICAMENTE en JSON válido. "
        'Estructura: {"resumen": "...", "kpis": {...}, "tabla": [[...]], '
        '"evidencia": {...}}'
    )

    def test_12_prompt_json_produce_reporte_valido(self):
        import json as _json
        from core.providers import respuesta_mock
        from core.schemas import ReporteAgente
        texto = respuesta_mock("mock:agentdesk-demo", self.PROMPT_JSON)
        reporte = ReporteAgente.model_validate(_json.loads(texto))
        self.assertTrue(all(isinstance(c, str) for f in reporte.tabla for c in f))
        self.assertTrue(reporte.kpis and reporte.evidencia)

    def test_13_determinista_y_sin_cifras_que_disparen_grounding(self):
        from core.providers import respuesta_mock
        a = respuesta_mock("mock:agentdesk-demo", self.PROMPT_JSON)
        b = respuesta_mock("mock:agentdesk-demo", self.PROMPT_JSON)
        self.assertEqual(a, b, "mismo prompt debe dar exactamente el mismo texto")
        import json as _json, re as _re
        evidencia = _json.loads(a)["evidencia"]
        numeros = [float(n) for v in evidencia.values()
                   for n in _re.findall(r"\d+(?:\.\d+)?", str(v))]
        self.assertFalse([n for n in numeros if n >= 1000],
                         "evidencia mock no debe citar cifras >=1000 (GroundingGuard)")

    def test_14_prompt_conversacional_sigue_siendo_texto(self):
        from core.providers import respuesta_mock
        texto = respuesta_mock("mock:agentdesk-demo", "Hola, como estas?")
        self.assertNotIn('"resumen"', texto)

    def test_15_pipeline_completo_sobrevive_con_mock(self):
        """realizar_tarea + pipeline real (Grounding incluido) con el mock."""
        from unittest.mock import patch
        from core.orchestrator import AgentBase
        from core.providers import respuesta_mock

        agente = AgentBase(
            {"id": "t_mock", "nombre": "Experto Degradado", "tipo_ia": "analitico",
             "area": "Test", "modelo": "mock:agentdesk-demo", "temperatura": 0.0,
             "idioma": "espanol", "prompt_base": "Eres un analista.",
             "siguiente_agente_id": None},
            None, "models/gemini-2.5-flash")

        async def _generar(prompt, temperatura=0.4, prioridad=2, modelo_preferido=None):
            texto = respuesta_mock("mock:agentdesk-demo", prompt)
            return {"texto": texto, "proveedor": "mock", "modelo": "mock:agentdesk-demo",
                    "intentos": ["mock:ok"], "degradado": True, "tokens_entrada": 1,
                    "tokens_salida": 1, "tokens_total": 2, "tokens_exactos": False}

        with patch("core.services.llm_service.llm_service.generar", side_effect=_generar):
            resultado = asyncio.run(
                agente.realizar_tarea("reporte_ventas",
                                      _datos_override={"ventas": {"mayo": 75000}}))
        self.assertIsNotNone(resultado, "el reporte mock debe sobrevivir el pipeline")


class TestEndpointResetCircuitos(unittest.TestCase):
    """POST /diagnostico/llm/reset: RBAC supervisor+ y reset real del singleton."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from core.api import app
        # Sin `with`: no disparar lifespan/startup (patron test_security)
        cls.client = TestClient(app, raise_server_exceptions=False)

    @staticmethod
    def _token(rol):
        from core.auth import crear_token
        return crear_token(f"test_reset_{rol}", rol)["token"]

    def test_10_endpoint_reset_exige_supervisor(self):
        r = self.client.post("/diagnostico/llm/reset", json={})
        self.assertEqual(r.status_code, 403)
        r = self.client.post(
            "/diagnostico/llm/reset", json={},
            headers={"Authorization": f"Bearer {self._token('viewer')}"},
        )
        self.assertEqual(r.status_code, 403)

    def test_11_endpoint_reset_cierra_circuito_del_singleton(self):
        from core.services.llm_service import llm_service
        llm_service.registrar_fallo("gemini", "clave vieja")
        llm_service.registrar_fallo("gemini", "clave vieja")
        self.assertFalse(llm_service.estado_circuitos()["gemini"]["activo"])

        r = self.client.post(
            "/diagnostico/llm/reset", json={"proveedor": "gemini"},
            headers={"Authorization": f"Bearer {self._token('supervisor')}"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reseteados"], ["gemini"])
        self.assertTrue(llm_service.estado_circuitos()["gemini"]["activo"])


if __name__ == "__main__":
    unittest.main()
