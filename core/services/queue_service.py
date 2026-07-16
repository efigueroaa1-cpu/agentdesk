"""
core/services/queue_service.py — Cola de Trabajos Pesados (Fase 8, ADR-0006;
Queue Mode y Circuit Breaker de Concurrencia extendidos en Fase 21, ADR-0019).

Implementación del QueuePort en modo dual:

  - LocalQueueService (defecto): ThreadPoolExecutor del proceso. Los PDFs,
    la analítica y todo trabajo síncrono pesado corren en hilos worker y el
    event loop de FastAPI queda libre — el Dashboard no se 'cuelga'.
  - Celery + Redis (planta): si AGENTDESK_QUEUE_URL está definida, el broker
    responde a un PING real (`_broker_disponible`, Fase 21) y celery está
    instalado, `encolar` delega en workers externos (procesos independientes,
    reinicio sin perder la API). Fallback transparente al modo local si falta
    cualquiera de las tres condiciones, dejando aviso.

Los endpoints NUNCA llaman lógica pesada directo: usan
`queue_service.ejecutar_pesado(fn, ...)` — regla vigilada por el Guardián.

Circuit Breaker de Concurrencia (Fase 21): `ejecutar_pesado`/`encolar` NUNCA
despachan trabajo si `resource_guard.puede_admitir_tarea()` dice que el host
está sobre el umbral crítico de CPU/RAM — incluso en modo Celery, porque
`ejecutar_pesado` SIEMPRE corre en el pool local del proceso API (ver
docstring de CeleryQueueService), así que el host que hay que proteger es
siempre el mismo.
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

# Circuit Breaker de Concurrencia (Fase 21): cuantos reintentos con espera
# antes de rechazar una tarea pesada por carga de host excesiva.
MAX_REINTENTOS_CARGA = 3
REINTENTO_ESPERA_S   = 0.3


class LocalQueueService:
    """QueuePort sobre un pool de hilos del propio proceso."""

    def __init__(self, max_workers: int = 4):
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="agentdesk-worker")
        self._jobs: dict[str, dict] = {}

    # ── Vía principal: pesado sin bloquear el event loop ──────────────────

    async def ejecutar_pesado(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        from core.services.resource_guard import puede_admitir_tarea, RecursosAgotadosError

        for intento in range(MAX_REINTENTOS_CARGA):
            if puede_admitir_tarea():
                break
            await asyncio.sleep(REINTENTO_ESPERA_S)
        else:
            raise RecursosAgotadosError(
                "Sistema sobrecargado (CPU/RAM sobre el umbral critico) — "
                "tarea pesada rechazada para proteger la estabilidad del host."
            )
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, lambda: fn(*args, **kwargs))

    # ── Jobs en segundo plano (fire-and-poll) ─────────────────────────────

    def encolar(self, nombre: str, fn: Callable[..., Any], *args, **kwargs) -> str:
        from core.services.resource_guard import puede_admitir_tarea

        job_id = str(uuid.uuid4())[:8]
        self._jobs[job_id] = {"job_id": job_id, "nombre": nombre,
                              "estado": "pendiente", "ts": utcnow().isoformat(),
                              "resultado": None, "error": None}

        if not puede_admitir_tarea():
            self._jobs[job_id]["estado"] = "rechazado_por_carga"
            self._jobs[job_id]["error"]  = ("Sistema sobrecargado (CPU/RAM sobre el "
                                            "umbral critico) — job no despachado.")
            logger.warning("QUEUE: job '%s' (%s) rechazado por carga de host", job_id, nombre)
            return job_id

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


def _broker_disponible(url: str) -> bool:
    """
    Fase 21 (ADR-0019): detección REAL de disponibilidad, no solo "la env
    var está seteada". Antes de esta fase, `crear_queue_service()` construía
    el cliente `Celery(...)` y confiaba en que una excepción de conexión
    apareciera ahí -- pero el cliente Celery es LAZY: no abre conexión al
    construirse, solo al despachar la primera tarea. Eso significa que con
    un broker apagado, el sistema quedaba "en modo distribuido" sin saberlo
    hasta el primer `encolar()` real en producción. Este PING explícito
    (timeout corto, best-effort) es lo que hace cierta la frase "detecta
    automáticamente si un broker está disponible" del pedido de la fase.
    """
    try:
        import redis
    except ImportError:
        logger.warning("QUEUE: paquete 'redis' no instalado — no se puede verificar "
                       "el broker; cola en modo local.")
        return False
    try:
        cliente = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        return bool(cliente.ping())
    except Exception as exc:
        logger.warning("QUEUE: broker Redis no responde (%s) — cola en modo local.", exc)
        return False


def crear_queue_service() -> LocalQueueService:
    """Factory: Celery si hay broker configurado, ALCANZABLE (ping real) e instalado; local si no."""
    broker = os.environ.get("AGENTDESK_QUEUE_URL", "").strip()
    if broker and _broker_disponible(broker):
        try:
            return CeleryQueueService(broker)
        except ImportError:
            logger.warning("celery no instalado — cola en modo local.")
        except Exception as exc:
            logger.warning("QUEUE: broker respondio al ping pero Celery fallo al conectar (%s) "
                           "— cola en modo local.", exc)
    return LocalQueueService()


# Instancia del proceso
queue_service = crear_queue_service()
