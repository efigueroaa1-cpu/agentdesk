"""
Suite unittest para los Guardrails del PipelineProcessor.
Usa IsolatedAsyncioTestCase (Python 3.8+) para métodos async nativos.

Ejecutar con:  python -m unittest test_pipeline.py -v
"""

import asyncio
import json
import time
import unittest

from core.log_config import configurar_logging
configurar_logging()

from google import genai
from config_api import API_KEY
from core.pipeline import (
    PipelineProcessor,
    TIMEOUT_FILTRO,
    measure_latency,
)
from core.orchestrator import Orquestador


# ── Fixtures compartidos ───────────────────────────────────────────────────────

RAW_VALIDO = {
    "reporte_ventas": {"Marzo": "$50,000", "Abril": "$62,000", "Mayo": "$75,000"},
    "estado_sistema": {"Amperaje": "12.5A", "Temperatura": "45C", "Estado": "Operativo"},
}

REPORTE_VALIDO = {
    "resumen": "Las ventas muestran un crecimiento sostenido del 20% mensual.",
    "kpis": {"Ventas_Mayo": "$75,000", "Crecimiento": "20%"},
    "tabla": [["Mes", "Ventas"], ["Mayo", "$75,000"]],
    "evidencia": {
        "Ventas_Mayo": "Valor de Mayo en reporte_ventas: $75,000",
    },
}


# ── Suite principal ────────────────────────────────────────────────────────────

class TestPipelineGuardrails(unittest.IsolatedAsyncioTestCase):

    async def test_01_cadena_completa_caso_exitoso(self):
        """Pipeline aprueba un reporte válido sin marcar integridad."""
        p = PipelineProcessor("Agente Test")
        resultado = await p.procesar(RAW_VALIDO, "respuesta única", REPORTE_VALIDO)
        self.assertIsNotNone(resultado, "Pipeline rechazó un reporte válido")
        self.assertNotIn("_integridad", resultado, "Marcó integridad sin razón")

    async def test_02_recursion_guard_detecta_bucle(self):
        """RecursionGuard aborta en el tercer intento con respuesta idéntica."""
        p = PipelineProcessor("Agente Bucle")
        texto = "exactamente la misma respuesta siempre"

        r1 = await p.procesar(RAW_VALIDO, texto, REPORTE_VALIDO)
        self.assertIsNotNone(r1, "Primer intento debería pasar")

        r2 = await p.procesar(RAW_VALIDO, texto, REPORTE_VALIDO)
        self.assertIsNotNone(r2, "Segundo intento debería pasar")

        r3 = await p.procesar(RAW_VALIDO, texto, REPORTE_VALIDO)
        self.assertIsNone(r3, "Tercer intento idéntico debería ser abortado")

    async def test_03_recursion_guard_no_aborta_con_variacion(self):
        """RecursionGuard no aborta cuando las respuestas varían."""
        p = PipelineProcessor("Agente Variado")
        for i in range(5):
            r = await p.procesar(RAW_VALIDO, f"respuesta distinta {i}", REPORTE_VALIDO)
            self.assertIsNotNone(r, f"Intento {i+1} con texto distinto no debería abortar")

    async def test_04_tone_guard_rechaza_coloquial(self):
        """ToneGuard rechaza un resumen con lenguaje no profesional."""
        p = PipelineProcessor("Agente Tono")
        reporte_coloquial = {
            "resumen": "Wow, las ventas están super geniales este mes, bro.",
            "kpis": {"Ventas": "$75,000"},
            "tabla": [["Mes", "Ventas"], ["Mayo", "$75,000"]],
        }
        resultado = await p.procesar(RAW_VALIDO, "texto ok", reporte_coloquial)
        self.assertIsNone(resultado, "ToneGuard debería rechazar lenguaje coloquial")

    async def test_05_tone_guard_aprueba_profesional(self):
        """ToneGuard aprueba un resumen con lenguaje formal."""
        p = PipelineProcessor("Agente Formal")
        resultado = await p.procesar(RAW_VALIDO, "texto ok", REPORTE_VALIDO)
        self.assertIsNotNone(resultado, "ToneGuard rechazó un reporte con tono profesional")

    async def test_06_logic_integrity_marca_discrepancia_100x(self):
        """LogicIntegrityFilter anota '_integridad' cuando un KPI excede 100× el raw."""
        p = PipelineProcessor("Agente Integridad")
        reporte_inflado = {
            "resumen": "Las ventas presentan resultados positivos este trimestre.",
            "kpis": {"Ventas_Infladas": "$99,000,000"},   # 99 M vs 75 K → ratio ~1320×
            "tabla": [["Mes", "Ventas"], ["Mayo", "$99,000,000"]],
            "evidencia": {
                "Ventas_Infladas": "Dato base de Mayo en reporte_ventas: $75,000",
            },
        }
        resultado = await p.procesar(RAW_VALIDO, "texto ok", reporte_inflado)
        self.assertIsNotNone(resultado, "LogicIntegrityFilter no debe abortar, solo anotar")
        self.assertIn("_integridad", resultado, "Debería marcar '_integridad'")
        self.assertIn("Error de Integridad", resultado["_integridad"])

    async def test_07_logic_integrity_no_marca_valores_validos(self):
        """LogicIntegrityFilter no anota cuando los KPIs son plausibles."""
        p = PipelineProcessor("Agente Limpio")
        resultado = await p.procesar(RAW_VALIDO, "texto ok", REPORTE_VALIDO)
        self.assertIsNotNone(resultado)
        self.assertNotIn("_integridad", resultado)

    async def test_08_execution_timeout_watchdog(self):
        """@measure_latency activa asyncio.TimeoutError cuando un filtro supera 5 s."""
        @measure_latency
        async def filtro_lento():
            await asyncio.sleep(TIMEOUT_FILTRO + 2)

        inicio = time.monotonic()
        with self.assertRaises(asyncio.TimeoutError):
            await filtro_lento()
        duracion = time.monotonic() - inicio
        self.assertLess(duracion, TIMEOUT_FILTRO + 1,
                        f"El watchdog tardó demasiado ({duracion:.2f}s)")

    async def test_09_measure_latency_registra_telemetria_json(self):
        """@measure_latency emite entradas JSON con filtro, duracion_s y status."""
        p = PipelineProcessor("Agente Telemetría")
        await p.procesar(RAW_VALIDO, "respuesta telemetria única", REPORTE_VALIDO)

        with open("logs/sistema.log", encoding="utf-8") as f:
            entradas = [
                json.loads(l)
                for l in f
                if l.strip().startswith("{") and '"filtro"' in l and '"duracion_s"' in l
            ]

        self.assertGreaterEqual(len(entradas), 3,
                                "Debería haber al menos 3 entradas de filtro en el log")
        for e in entradas[-3:]:
            self.assertIn("filtro",     e, "Falta campo 'filtro'")
            self.assertIn("duracion_s", e, "Falta campo 'duracion_s'")
            self.assertIn("status",     e, "Falta campo 'status'")
            self.assertIsInstance(e["duracion_s"], float)

    async def test_10_pipeline_real_gemini_end_to_end(self):
        """Pipeline completo con llamada real a Gemini — todos los guardrails activos."""
        client = genai.Client(api_key=API_KEY)
        pager = await client.aio.models.list()
        model_name = None
        async for m in pager:
            if "generateContent" in (m.supported_actions or []):
                model_name = m.name
                break

        self.assertIsNotNone(model_name, "No se encontró ningún modelo disponible")

        app = Orquestador("config.json", client, model_name)
        data = await app.agentes["agente_finanzas_01"].realizar_tarea("reporte_ventas")

        self.assertIsNotNone(data, "El pipeline abortó en un caso real válido")
        self.assertIn("resumen", data)
        self.assertIn("kpis",    data)
        self.assertIn("tabla",   data)
        self.assertIsInstance(data["kpis"], dict)
        self.assertGreater(len(data["tabla"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
