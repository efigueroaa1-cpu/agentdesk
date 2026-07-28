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
import os
import tempfile
import time
import unittest
from pathlib import Path

# Estos tests prueban Map-Reduce, no el Circuit Breaker de Concurrencia (que
# tiene su propia suite en test_resource_guard.py). Umbrales al 100% para que
# una maquina de CI/dev genuinamente cargada (RAM >90% real) no los vuelva
# flaky -- el codigo del breaker sigue ejecutandose, solo que nunca rechaza.
os.environ["AGENTDESK_CPU_MAX_PCT"] = "100"
os.environ["AGENTDESK_MEM_MAX_PCT"] = "100"

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
        # Marcas de tiempo para verificar CONCURRENCIA de forma estructural
        # (solapamiento), sin depender del wall-clock total (2026-07-28).
        self.t_inicio: float | None = None
        self.t_fin:    float | None = None

    async def chat_libre(self, mensaje, contexto_archivo="", sesion_id="default",
                          agente_id_clave="", user_id="anonimo") -> str:
        self.t_inicio = time.monotonic()
        await asyncio.sleep(self._delay_s)
        self.t_fin = time.monotonic()
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
            "trabajador.1": _AgenteFake("Trabajador1", respuesta="ok-1", delay_s=0.5),
            "trabajador.2": _AgenteFake("Trabajador2", respuesta="ok-2", delay_s=0.5),
        }
        svc = self._servicio(agentes)
        latidos = []

        async def latir():
            # Latidos durante toda la ventana del worker (0.5s) para verificar
            # que el loop principal no queda bloqueado.
            for _ in range(20):
                latidos.append(time.monotonic())
                await asyncio.sleep(0.03)

        _, _ = await asyncio.gather(
            svc.ejecutar("lider", ["trabajador.1", "trabajador.2"], "tarea", user_id="op"),
            latir(),
        )

        # Paralelismo real, medido ESTRUCTURALMENTE (independiente del wall-clock,
        # 2026-07-28): ambos workers ARRANCARON antes de que CUALQUIERA terminara
        # -> sus ventanas se solapan. En ejecucion serial el 2do worker arranca
        # recien cuando el 1ro termino, luego max(inicios) >= min(fines). Este
        # criterio no depende de la latencia de recursos del runner (elimina el
        # falso rojo por carga de CPU/RAM sin perder poder discriminante).
        inicios = [a.t_inicio for a in (agentes["trabajador.1"], agentes["trabajador.2"])]
        fines   = [a.t_fin    for a in (agentes["trabajador.1"], agentes["trabajador.2"])]
        self.assertTrue(all(t is not None for t in inicios + fines), "los workers no corrieron")
        self.assertLess(max(inicios), min(fines),
                        "Los workers no se solaparon -> corrieron en serie, no en paralelo")

        # El loop no quedo bloqueado: un salto entre latidos ~= la duracion del
        # worker (0.5s) delataria un bloqueo; 0.35s tolera el jitter de scheduling
        # bajo carga y aun cazaria ese bloqueo.
        intervalos = [b - a for a, b in zip(latidos, latidos[1:])]
        self.assertLess(max(intervalos), 0.35,
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
