# -*- coding: utf-8 -*-
"""
tests/scale/test_resource_guard.py — Circuit Breaker de Concurrencia
(Fase 21, ADR-0019).

Verifica el límite dinámico de tareas concurrentes basado en carga real de
CPU/RAM (psutil) y el decorador declarativo de costo de recursos.
"""
import asyncio
import os
import unittest
from unittest.mock import patch

from core.services import resource_guard
from core.services.queue_service import LocalQueueService


class TestCostoRecursos(unittest.TestCase):

    def test_01_decorador_adjunta_metadata_sin_alterar_comportamiento(self):
        @resource_guard.costo_recursos(cpu="alto", memoria="bajo")
        def _fn(x):
            return x * 2

        self.assertEqual(_fn(3), 6)
        self.assertEqual(_fn.costo_recursos, {"cpu": "alto", "memoria": "bajo"})

    def test_02_niveles_invalidos_rechazados_en_definicion(self):
        with self.assertRaises(ValueError):
            @resource_guard.costo_recursos(cpu="extremo", memoria="bajo")
            def _fn():
                pass


class TestCargaActual(unittest.TestCase):

    def test_01_con_psutil_disponible_reporta_metricas_reales(self):
        carga = resource_guard.carga_actual()
        self.assertIn("cpu_pct", carga)
        self.assertIn("mem_pct", carga)
        self.assertIsInstance(carga["psutil_disponible"], bool)

    def test_02_sin_psutil_degrada_a_siempre_admite(self):
        with patch.dict("sys.modules", {"psutil": None}):
            carga = resource_guard.carga_actual()
        self.assertFalse(carga["psutil_disponible"])
        self.assertEqual(carga["cpu_pct"], 0.0)
        self.assertEqual(carga["mem_pct"], 0.0)


class TestPuedeAdmitirTarea(unittest.TestCase):

    def test_01_carga_baja_admite(self):
        with patch.object(resource_guard, "carga_actual",
                          return_value={"cpu_pct": 10.0, "mem_pct": 10.0, "psutil_disponible": True}):
            self.assertTrue(resource_guard.puede_admitir_tarea())

    def test_02_carga_critica_no_admite(self):
        with patch.object(resource_guard, "carga_actual",
                          return_value={"cpu_pct": 99.0, "mem_pct": 50.0, "psutil_disponible": True}):
            self.assertFalse(resource_guard.puede_admitir_tarea())

    def test_03_umbral_configurable_via_env(self):
        os.environ["AGENTDESK_CPU_MAX_PCT"] = "50"
        try:
            with patch.object(resource_guard, "carga_actual",
                              return_value={"cpu_pct": 60.0, "mem_pct": 10.0, "psutil_disponible": True}):
                self.assertFalse(resource_guard.puede_admitir_tarea())
        finally:
            del os.environ["AGENTDESK_CPU_MAX_PCT"]

    def test_04_umbral_invalido_degrada_al_default(self):
        os.environ["AGENTDESK_CPU_MAX_PCT"] = "no-es-un-numero"
        try:
            umbral = resource_guard._umbral("AGENTDESK_CPU_MAX_PCT", resource_guard.CPU_MAX_PORCENTAJE_DEFECTO)
        finally:
            del os.environ["AGENTDESK_CPU_MAX_PCT"]
        self.assertEqual(umbral, resource_guard.CPU_MAX_PORCENTAJE_DEFECTO)


class TestCircuitoEnQueueService(unittest.IsolatedAsyncioTestCase):
    """El Circuit Breaker de Concurrencia debe bloquear tareas pesadas de verdad."""

    async def test_01_ejecutar_pesado_rechaza_bajo_carga_critica_sostenida(self):
        cola = LocalQueueService()
        with patch.object(resource_guard, "puede_admitir_tarea", return_value=False), \
             patch("core.services.queue_service.REINTENTO_ESPERA_S", 0.01):
            with self.assertRaises(resource_guard.RecursosAgotadosError):
                await cola.ejecutar_pesado(lambda: "no-deberia-correr")

    async def test_02_ejecutar_pesado_corre_cuando_hay_margen(self):
        cola = LocalQueueService()
        with patch.object(resource_guard, "puede_admitir_tarea", return_value=True):
            resultado = await cola.ejecutar_pesado(lambda: "corrio-ok")
        self.assertEqual(resultado, "corrio-ok")

    def test_03_encolar_marca_rechazado_por_carga_sin_despachar(self):
        cola = LocalQueueService()
        ejecutado = []

        def _fn():
            ejecutado.append(True)
            return "no-deberia-correr"

        with patch.object(resource_guard, "puede_admitir_tarea", return_value=False):
            job_id = cola.encolar("job_bajo_carga", _fn)

        self.assertEqual(cola.estado(job_id)["estado"], "rechazado_por_carga")
        self.assertEqual(ejecutado, [], "La funcion no debio despacharse bajo carga critica")


if __name__ == "__main__":
    unittest.main()
