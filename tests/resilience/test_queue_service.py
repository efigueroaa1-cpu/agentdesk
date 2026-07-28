# -*- coding: utf-8 -*-
"""
tests/resilience/test_queue_service.py — Cola de Trabajos Pesados (Fase 8).

El event loop debe permanecer LIBRE mientras el trabajo pesado corre en el
pool de workers — esa es la garantía de que el Dashboard nunca se cuelga.
"""
import asyncio
import time
import unittest
from unittest.mock import patch

from core.ports.queue_port import QueuePort
from core.services.queue_service import LocalQueueService

# Los tests de CICLO DE VIDA del job (encolar -> ejecutar -> completado/error)
# deben ser DETERMINISTAS e independientes de la carga real del host: el
# circuito de concurrencia (puede_admitir_tarea, RAM/CPU >90%) rechazaba jobs
# bajo la carga del runner CI DESPUES de los 347 tests -> "rechazado_por_carga"
# en vez de "completado" -> falso rojo intermitente (2026-07-28). Se mockea el
# guard a True aqui; su comportamiento REAL de rechazo se prueba aparte, tambien
# de forma determinista (test_08), y en tests/scale/test_resource_guard.
_ADMITIR_SIEMPRE = patch("core.services.resource_guard.puede_admitir_tarea",
                         return_value=True)


def _trabajo_pesado(duracion_s: float = 0.5) -> str:
    time.sleep(duracion_s)   # trabajo síncrono bloqueante (PDF, analítica)
    return "reporte-listo"


class TestQueueService(unittest.TestCase):

    def test_01_cumple_el_contrato_queue_port(self):
        self.assertIsInstance(LocalQueueService(), QueuePort)

    def test_02_event_loop_libre_durante_trabajo_pesado(self):
        """Mientras el PDF 'se genera' (0.5s), el loop atiende otras corutinas."""
        latidos = []

        async def latir():
            for _ in range(10):
                latidos.append(time.monotonic())
                await asyncio.sleep(0.03)

        async def escenario():
            cola = LocalQueueService()
            resultado, _ = await asyncio.gather(
                cola.ejecutar_pesado(_trabajo_pesado, 0.5),
                latir(),
            )
            return resultado

        resultado = asyncio.run(asyncio.wait_for(escenario(), timeout=15))
        self.assertEqual(resultado, "reporte-listo")
        # Si el loop se hubiera bloqueado 0.5s, los latidos vendrían agrupados
        # al final; con el loop libre laten cada ~30ms durante el trabajo.
        intervalos = [b - a for a, b in zip(latidos, latidos[1:])]
        self.assertLess(max(intervalos), 0.4,
                        "El event loop quedo bloqueado por el trabajo pesado")

    @_ADMITIR_SIEMPRE
    def test_03_job_en_segundo_plano_con_estado(self, _m):
        cola   = LocalQueueService()
        job_id = cola.encolar("reporte_masivo", _trabajo_pesado, 0.2)
        for _ in range(50):
            if cola.estado(job_id)["estado"] == "completado":
                break
            time.sleep(0.05)
        self.assertEqual(cola.estado(job_id)["estado"], "completado")
        self.assertEqual(cola.resultado(job_id), "reporte-listo")

    @_ADMITIR_SIEMPRE
    def test_04_job_fallido_reporta_error_sin_tumbar_nada(self, _m):
        def _explota():
            raise RuntimeError("boom-pdf")

        cola   = LocalQueueService()
        job_id = cola.encolar("reporte_roto", _explota)
        for _ in range(50):
            if cola.estado(job_id)["estado"] in ("error", "completado"):
                break
            time.sleep(0.05)
        st = cola.estado(job_id)
        self.assertEqual(st["estado"], "error")
        self.assertIn("boom-pdf", st["error"])

    @patch("core.services.resource_guard.puede_admitir_tarea", return_value=False)
    def test_08_host_sobrecargado_rechaza_el_job_de_forma_determinista(self, _m):
        """El rechazo por carga se prueba MOCKEANDO el guard (no dependiendo de
        la RAM real del host) -- deterministico, sin flake."""
        cola   = LocalQueueService()
        job_id = cola.encolar("reporte_masivo", _trabajo_pesado, 0.2)
        st = cola.estado(job_id)
        self.assertEqual(st["estado"], "rechazado_por_carga")
        self.assertIn("sobrecargado", st["error"].lower())

    def test_05_job_inexistente_lookup_error(self):
        with self.assertRaises(LookupError):
            LocalQueueService().estado("no-existe")


if __name__ == "__main__":
    unittest.main()
