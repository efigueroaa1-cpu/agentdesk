"""
core/services/map_reduce_service.py — Orquestación Paralela Map-Reduce
(Fase 21, ADR-0019).

Un agente 'Líder' reparte la MISMA tarea entre N agentes 'trabajadores' en
paralelo (Map) y consolida sus respuestas en un único resultado (Reduce) —
pensado para análisis de grandes volúmenes de datos industriales donde un
solo agente, secuencial, sería el cuello de botella.

Decisión de diseño clave: cada trabajador corre en su PROPIO hilo aislado
del pool de `queue_service` (`ThreadPoolExecutor`), no como corutinas de
`asyncio.gather` compartiendo el mismo hilo del event loop. Dos motivos:

  1. Aislamiento de fallos REAL: si un worker revienta (excepción no
     controlada, cuelgue de un SDK síncrono de terceros), no puede tumbar
     ni bloquear a los demás workers ni al hilo del event loop principal.
  2. El Circuit Breaker de Concurrencia (`resource_guard`) protege TODO
     trabajo que pasa por `queue_service.ejecutar_pesado()` — despachar N
     workers como N llamadas a `ejecutar_pesado()` hace que un Map-Reduce
     de 50 agentes respete el mismo límite dinámico de CPU/RAM que
     protege un solo PDF pesado, sin código nuevo de límite.

El event loop del orquestador nunca bloquea: `ejecutar_pesado()` envuelve
`loop.run_in_executor()`, y `asyncio.gather` sobre N de esas llamadas espera
sin ocupar el hilo del loop mientras los workers corren de verdad en
paralelo en sus propios hilos.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Callable

from core.services.resource_guard import costo_recursos

logger = logging.getLogger(__name__)


@dataclass
class ResultadoWorker:
    agente_id: str
    ok: bool
    texto: str = ""
    error: str = ""
    hilo: str = ""


def _ejecutar_subtarea_en_hilo(agente, agente_id: str, prompt: str, user_id: str) -> ResultadoWorker:
    """
    Corre DENTRO de un hilo worker del pool de `queue_service` (invocada via
    `ejecutar_pesado`, nunca directo). `chat_libre` es async y este hilo no
    tiene event loop propio corriendo -- `asyncio.run()` le crea uno nuevo,
    aislado del loop principal del proceso. Es lo que hace que este worker
    sea un aislamiento REAL (hilo de SO propio + loop propio), no una
    ilusión de paralelismo sobre el mismo hilo.
    """
    hilo = threading.current_thread().name
    try:
        texto = asyncio.run(agente.chat_libre(
            prompt, sesion_id=f"mapreduce:{agente_id}",
            agente_id_clave=agente_id, user_id=user_id,
        ))
        return ResultadoWorker(agente_id=agente_id, ok=True, texto=texto, hilo=hilo)
    except Exception as exc:
        logger.warning("MAP_REDUCE: worker '%s' fallo (%s)", agente_id, exc)
        return ResultadoWorker(agente_id=agente_id, ok=False, error=str(exc), hilo=hilo)


@costo_recursos(cpu="medio", memoria="medio")
def _reducir_resultados(resultados: list[ResultadoWorker]) -> dict:
    """
    Fase Reduce: consolida N respuestas de workers en un único resultado.
    Costo declarado medio/medio (Fase 21, [SCALE-LIMITS]) -- agregar texto
    de N agentes (potencialmente docenas en un dataset industrial grande)
    es trabajo real de CPU/memoria, no gratis, aunque hoy sea una
    concatenación simple.
    """
    exitosos = [r for r in resultados if r.ok]
    fallidos = [r for r in resultados if not r.ok]
    return {
        "ok": len(exitosos) > 0,
        "total_workers": len(resultados),
        "exitosos": len(exitosos),
        "fallidos": len(fallidos),
        "hilos_usados": sorted({r.hilo for r in resultados}),
        "resumen": "\n---\n".join(f"[{r.agente_id}] {r.texto}" for r in exitosos),
        "detalle": [
            {"agente_id": r.agente_id, "ok": r.ok, "error": r.error, "hilo": r.hilo}
            for r in resultados
        ],
    }


class MapReduceService:
    """Orquestación paralela: un Líder despacha a N trabajadores y consolida."""

    def __init__(self, get_orquestador: Callable[[], object | None], queue_service=None):
        self._get_orquestador = get_orquestador
        if queue_service is None:
            from core.services.queue_service import queue_service as _qs
            queue_service = _qs
        self._queue = queue_service

    async def ejecutar(self, lider_id: str, trabajadores_ids: list[str], prompt: str,
                        user_id: str = "anonimo") -> dict:
        orq = self._get_orquestador()
        if orq is None or not hasattr(orq, "agentes"):
            raise RuntimeError("Orquestador no disponible para Map-Reduce.")
        if lider_id not in orq.agentes:
            raise RuntimeError(f"Agente Lider '{lider_id}' no existe.")
        if not trabajadores_ids:
            raise ValueError("Map-Reduce requiere al menos un agente trabajador.")

        trabajadores = []
        for tid in trabajadores_ids:
            agente = orq.agentes.get(tid)
            if agente is None:
                raise RuntimeError(f"Agente trabajador '{tid}' no existe.")
            trabajadores.append((tid, agente))

        import time as _time
        from core.telemetry_otel import medir_paso

        # MAP: cada trabajador se despacha a su propio hilo aislado, EN
        # PARALELO, sin bloquear el event loop -- ver docstring del modulo.
        t0 = _time.monotonic()
        with medir_paso("mapreduce.map", lider=lider_id, workers=len(trabajadores)):
            tareas = [
                self._queue.ejecutar_pesado(_ejecutar_subtarea_en_hilo, agente, tid, prompt, user_id)
                for tid, agente in trabajadores
            ]
            resultados: list[ResultadoWorker] = list(await asyncio.gather(*tareas))
        t_map = _time.monotonic() - t0

        # REDUCE
        t0 = _time.monotonic()
        with medir_paso("mapreduce.reduce", lider=lider_id, workers=len(trabajadores)):
            consolidado = _reducir_resultados(resultados)
        t_reduce = _time.monotonic() - t0

        # Prometheus (Fase 22, ADR-0020): latencia por fase + workers por
        # resultado, best-effort — la base de los dashboards de Grafana.
        try:
            from core.metrics_prometheus import registrar_mapreduce
            registrar_mapreduce(t_map, t_reduce,
                                consolidado["exitosos"], consolidado["fallidos"])
        except Exception as exc:
            logger.warning("MAP_REDUCE: metricas Prometheus no actualizadas (%s)", exc)

        self._auditar(lider_id, trabajadores_ids, prompt, consolidado, user_id)
        return consolidado

    @staticmethod
    def _auditar(lider_id: str, trabajadores_ids: list[str], prompt: str,
                  consolidado: dict, user_id: str) -> None:
        """Traza forense best-effort del Map-Reduce completo (ADR-0007/0019)."""
        from core.services.audit_service import registrar_interaccion
        registrar_interaccion(
            tipo="map_reduce", agente_id=lider_id, prompt=prompt,
            respuesta=consolidado.get("resumen", "")[:2000], user_id=user_id,
            contexto=f"map_reduce:{','.join(trabajadores_ids)}",
            veredicto_guardrail="no_aplica",
        )
