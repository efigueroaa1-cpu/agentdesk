"""
core/ports/queue_port.py — Puerto de Cola de Trabajos Pesados (Fase 8, ADR-0006).

Contrato para delegar tareas de larga duración (PDFs pesados, analítica
masiva, reportes Gantt) fuera del hilo del event loop de la API, de modo que
el Dashboard nunca se sienta 'colgado'.

Adaptadores:
  - Local (defecto): pool de hilos del proceso — el event loop queda libre.
  - Celery + Redis (planta): workers independientes, activado por
    AGENTDESK_QUEUE_URL=redis://host:6379/0.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class QueuePort(Protocol):
    """Ejecución diferida de trabajo pesado, agnóstica del broker."""

    async def ejecutar_pesado(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        """
        Ejecuta `fn` (síncrona y CPU/IO-pesada) SIN bloquear el event loop y
        espera su resultado. Es la vía obligatoria para lógica pesada
        invocada desde endpoints (el Guardián lo hace cumplir en api.py).
        """
        ...

    def encolar(self, nombre: str, fn: Callable[..., Any], *args, **kwargs) -> str:
        """Encola un trabajo en segundo plano y retorna su job_id."""
        ...

    def estado(self, job_id: str) -> dict:
        """{'job_id', 'estado': pendiente|ejecutando|completado|error, ...}."""
        ...

    def resultado(self, job_id: str) -> Any:
        """Resultado de un job completado. LookupError si no existe."""
        ...
