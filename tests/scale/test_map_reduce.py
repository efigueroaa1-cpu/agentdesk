# -*- coding: utf-8 -*-
"""
tests/scale/test_map_reduce.py — Orquestación Paralela Map-Reduce (Fase 21, ADR-0019).

Criterio de éxito de la fase: el sistema debe demostrar la ejecución de una
tarea compleja distribuida en DOS workers simulados (hilos aislados) y el
'Líder' debe recibir el resultado consolidado SIN bloquear el event loop
principal del orquestador.

Este test demuestra las tres partes literalmente, no solo "no crasheo":
  1. Dos workers = DOS HILOS de sistema operativo distintos (no asyncio
     concurrency compartiendo un solo hilo) -- verificado leyendo
     `hilos_usados` del resultado consolidado.
  2. El event loop principal sigue libre mientras el Map corre -- mismo
     patrón de "latidos" que tests/resilience/test_queue_service.py
     (Fase 8): una corutina de heartbeat sigue tickeando cada ~30ms durante
     todo el Map-Reduce.
  3. El Líder recibe un resultado CONSOLIDADO (Reduce) -- no las respuestas
     crudas de cada worker por separado.

Usa una base SQLite temporal para la traza de auditoría — no toca la DB
real del usuario.
"""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path

import core.database as db
from core.services import audit_service
from core.services.map_reduce_service import MapReduceService
from core.services.queue_service import LocalQueueService


class _AgenteFake:
    """Doble de AgentBase: chat_libre async con demora simulada, sin red."""

    def __init__(self, nombre: str, respuesta: str = "", falla: bool = False, delay_s: float = 0.3):
        self.nombre   = nombre
        self._respuesta = respuesta
        self._falla    = falla
        self._delay_s  = delay_s

    async def chat_libre(self, mensaje, contexto_archivo="", sesion_id="default",
                          agente_id_clave="", user_id="anonimo") -> str:
        await asyncio.sleep(self._delay_s)
        if self._falla:
            raise RuntimeError(f"worker '{self.nombre}' simulando fallo")
        return self._respuesta


class _OrqFake:
    def __init__(self, agentes: dict):
        self.agentes = agentes


class TestMapReduce(unittest.IsolatedAsyncioTestCase):
    """Criterio de éxito de la Fase 21, ejercitado end-to-end."""

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "map_reduce_test.db")

    def _servicio(self, agentes: dict) -> MapReduceService:
        orq = _OrqFake(agentes)
        return MapReduceService(get_orquestador=lambda: orq, queue_service=LocalQueueService())

    async def test_01_dos_workers_en_hilos_aislados_resultado_consolidado(self):
        """El Lider despacha a 2 trabajadores en paralelo y recibe el Reduce."""
        agentes = {
            "lider":       _AgenteFake("Lider"),
            "trabajador.1": _AgenteFake("Trabajador1", respuesta="Sector Norte: 120 unidades"),
            "trabajador.2": _AgenteFake("Trabajador2", respuesta="Sector Sur: 95 unidades"),
        }
        svc = self._servicio(agentes)

        consolidado = await svc.ejecutar(
            "lider", ["trabajador.1", "trabajador.2"],
            "Analiza tu sector y reporta unidades producidas.",
            user_id="op.planta",
        )

        self.assertTrue(consolidado["ok"])
        self.assertEqual(consolidado["total_workers"], 2)
        self.assertEqual(consolidado["exitosos"], 2)
        self.assertEqual(consolidado["fallidos"], 0)

        # Criterio de exito, parte 1: DOS HILOS DE VERDAD, no el mismo hilo
        # dos veces -- aislamiento real, no asyncio.gather sobre 1 hilo.
        self.assertEqual(len(consolidado["hilos_usados"]), 2,
                          "Cada worker debe correr en su propio hilo aislado")

        # Criterio de exito, parte 3: el Lider recibe el CONSOLIDADO.
        self.assertIn("Sector Norte", consolidado["resumen"])
        self.assertIn("Sector Sur", consolidado["resumen"])

    async def test_02_event_loop_libre_durante_el_map(self):
        """Mientras 2 workers 'trabajan' (0.3s c/u), el loop sigue atendiendo otras corutinas."""
        agentes = {
            "lider":       _AgenteFake("Lider"),
            "trabajador.1": _AgenteFake("Trabajador1", respuesta="ok-1", delay_s=0.3),
            "trabajador.2": _AgenteFake("Trabajador2", respuesta="ok-2", delay_s=0.3),
        }
        svc = self._servicio(agentes)
        latidos = []

        async def latir():
            for _ in range(10):
                latidos.append(time.monotonic())
                await asyncio.sleep(0.03)

        inicio = time.monotonic()
        _, _ = await asyncio.gather(
            svc.ejecutar("lider", ["trabajador.1", "trabajador.2"], "tarea", user_id="op"),
            latir(),
        )
        duracion = time.monotonic() - inicio

        # Paralelismo real: 2 workers de 0.3s corren EN PARALELO (~0.3s), no
        # secuencial (~0.6s) -- confirma que de verdad son hilos concurrentes.
        self.assertLess(duracion, 0.55, "Los workers no corrieron en paralelo")

        intervalos = [b - a for a, b in zip(latidos, latidos[1:])]
        self.assertLess(max(intervalos), 0.25,
                        "El event loop principal quedo bloqueado durante el Map-Reduce")

    async def test_03_worker_que_falla_no_tumba_a_los_demas(self):
        """Aislamiento de fallos: un worker roto no afecta a los sanos ni al Reduce."""
        agentes = {
            "lider":       _AgenteFake("Lider"),
            "trabajador.1": _AgenteFake("Trabajador1", respuesta="ok", falla=False),
            "trabajador.2": _AgenteFake("Trabajador2", falla=True),
        }
        svc = self._servicio(agentes)

        consolidado = await svc.ejecutar(
            "lider", ["trabajador.1", "trabajador.2"], "tarea", user_id="op",
        )

        self.assertTrue(consolidado["ok"], "Al menos un worker exitoso -> resultado sigue siendo util")
        self.assertEqual(consolidado["exitosos"], 1)
        self.assertEqual(consolidado["fallidos"], 1)

    async def test_04_auditoria_registra_el_mapreduce_completo(self):
        agentes = {
            "lider":       _AgenteFake("Lider"),
            "trabajador.1": _AgenteFake("Trabajador1", respuesta="dato-A"),
            "trabajador.2": _AgenteFake("Trabajador2", respuesta="dato-B"),
        }
        svc = self._servicio(agentes)
        await svc.ejecutar("lider", ["trabajador.1", "trabajador.2"], "tarea", user_id="op.auditoria")

        trazas = audit_service.consultar(agente_id="lider", user_id="op.auditoria", limit=5)
        self.assertTrue(trazas, "El Map-Reduce completo debe dejar una traza de auditoria")
        self.assertEqual(trazas[0]["tipo"], "map_reduce")

    async def test_05_requiere_al_menos_un_trabajador(self):
        svc = self._servicio({"lider": _AgenteFake("Lider")})
        with self.assertRaises(ValueError):
            await svc.ejecutar("lider", [], "tarea", user_id="op")

    async def test_06_lider_inexistente_rechaza(self):
        svc = self._servicio({"trabajador.1": _AgenteFake("T1")})
        with self.assertRaises(RuntimeError):
            await svc.ejecutar("no-existe", ["trabajador.1"], "tarea", user_id="op")


if __name__ == "__main__":
    unittest.main()
