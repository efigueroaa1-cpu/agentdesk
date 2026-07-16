# -*- coding: utf-8 -*-
"""
tests/resilience/test_llm_fallback.py — Resiliencia de Inteligencia (Fase 8).

Criterio de éxito de la fase: una tarea de reporte se completa aunque el
proveedor de IA principal falle a mitad del proceso.

Correr:  python -m unittest tests.resilience.test_llm_fallback -v
"""
import asyncio
import unittest

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


if __name__ == "__main__":
    unittest.main()
