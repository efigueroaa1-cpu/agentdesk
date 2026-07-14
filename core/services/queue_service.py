"""
core/services/queue_service.py — Cola de Trabajos Pesados (Fase 8, ADR-0006).

Implementación del QueuePort en modo dual:

  - LocalQueueService (defecto): ThreadPoolExecutor del proceso. Los PDFs,
    la analítica y todo trabajo síncrono pesado corren en hilos worker y el
    event loop de FastAPI queda libre — el Dashboard no se 'cuelga'.
  - Celery + Redis (planta): si AGENTDESK_QUEUE_URL está definida y celery
    instalado, `encolar` delega en workers externos (procesos independientes,
    reinicio sin perder la API). Fallback transparente al modo local si falta
    la infraestructura, dejando aviso.

Los endpoints NUNCA llaman lógica pesada directo: usan
`queue_service.ejecutar_pesado(fn, ...)` — regla vigilada por el Guardián.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from core.timeutil import utcnow

logger = logging.getLogger(__name__)


class LocalQueueService:
    """QueuePort sobre un pool de hilos del propio proceso."""

    def __init__(self, max_workers: int = 4):
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="agentdesk-worker")
        self._jobs: dict[str, dict] = {}

    # ── Vía principal: pesado sin bloquear el event loop ──────────────────

    async def ejecutar_pesado(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, lambda: fn(*args, **kwargs))

    # ── Jobs en segundo plano (fire-and-poll) ─────────────────────────────

    def encolar(self, nombre: str, fn: Callable[..., Any], *args, **kwargs) -> str:
        job_id = str(uuid.uuid4())[:8]
        self._jobs[job_id] = {"job_id": job_id, "nombre": nombre,
                              "estado": "pendiente", "ts": utcnow().isoformat(),
                              "resultado": None, "error": None}

        def _correr():
            self._jobs[job_id]["estado"] = "ejecutando"
            try:
                self._jobs[job_id]["resultado"] = fn(*args, **kwargs)
                self._jobs[job_id]["estado"]    = "completado"
            except Exception as exc:
                self._jobs[job_id]["error"]  = str(exc)
                self._jobs[job_id]["estado"] = "error"
                logger.warning("QUEUE: job '%s' (%s) fallo: %s", job_id, nombre, exc)

        self._pool.submit(_correr)
        return job_id

    def estado(self, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        if job is None:
            raise LookupError(f"Job '{job_id}' no encontrado.")
        return {k: v for k, v in job.items() if k != "resultado"}

    def resultado(self, job_id: str) -> Any:
        job = self._jobs.get(job_id)
        if job is None:
            raise LookupError(f"Job '{job_id}' no encontrado.")
        return job["resultado"]


class CeleryQueueService(LocalQueueService):
    """
    QueuePort sobre Celery + Redis (workers independientes de planta).
    `ejecutar_pesado` conserva el pool local (respuesta síncrona rápida);
    `encolar` delega en el broker para trabajos batch de larga duración.
    """

    def __init__(self, broker_url: str, max_workers: int = 4):
        super().__init__(max_workers=max_workers)
        from celery import Celery   # ImportError la maneja crear_queue_service
        self._celery = Celery("agentdesk", broker=broker_url, backend=broker_url)
        logger.info("QUEUE: Celery conectado a %s", broker_url.split("@")[-1])

    def encolar(self, nombre: str, fn: Callable[..., Any], *args, **kwargs) -> str:
        tarea = self._celery.task(fn, name=f"agentdesk.{nombre}")
        return tarea.delay(*args, **kwargs).id

    def estado(self, job_id: str) -> dict:
        r = self._celery.AsyncResult(job_id)
        mapa = {"PENDING": "pendiente", "STARTED": "ejecutando",
                "SUCCESS": "completado", "FAILURE": "error"}
        return {"job_id": job_id, "estado": mapa.get(r.state, r.state.lower())}

    def resultado(self, job_id: str) -> Any:
        return self._celery.AsyncResult(job_id).result


def crear_queue_service() -> LocalQueueService:
    """Factory: Celery si hay broker configurado e instalado; local si no."""
    broker = os.environ.get("AGENTDESK_QUEUE_URL", "").strip()
    if broker:
        try:
            return CeleryQueueService(broker)
        except ImportError:
            logger.warning("celery/redis no instalados — cola en modo local.")
        except Exception as exc:
            logger.warning("QUEUE: broker inaccesible (%s) — cola en modo local.", exc)
    return LocalQueueService()


# Instancia del proceso
queue_service = crear_queue_service()
