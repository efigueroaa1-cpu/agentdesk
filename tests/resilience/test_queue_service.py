# -*- coding: utf-8 -*-
"""
tests/resilience/test_queue_service.py — Cola de Trabajos Pesados (Fase 8).

El event loop debe permanecer LIBRE mientras el trabajo pesado corre en el
pool de workers — esa es la garantía de que el Dashboard nunca se cuelga.
"""
import asyncio
import time
import unittest

from core.ports.queue_port import QueuePort
from core.services.queue_service import LocalQueueService


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

    def test_03_job_en_segundo_plano_con_estado(self):
        cola   = LocalQueueService()
        job_id = cola.encolar("reporte_masivo", _trabajo_pesado, 0.2)
        for _ in range(50):
            if cola.estado(job_id)["estado"] == "completado":
                break
            time.sleep(0.05)
        self.assertEqual(cola.estado(job_id)["estado"], "completado")
        self.assertEqual(cola.resultado(job_id), "reporte-listo")

    def test_04_job_fallido_reporta_error_sin_tumbar_nada(self):
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

    def test_05_job_inexistente_lookup_error(self):
        with self.assertRaises(LookupError):
            LocalQueueService().estado("no-existe")


if __name__ == "__main__":
    unittest.main()
