"""
core/ports/orchestrator_port.py — Puerto del Motor de Orquestación (ADR-0003).

Lo que los adaptadores de entrada (HTTP, webhook, CLI) necesitan del cerebro
de AgentDesk: ejecutar tareas, conversar (con y sin streaming) y atender
comandos remotos. Implementado por core/services/orchestrator_service.py.

Contrato de errores: `ejecutar_tarea` lanza LookupError si el agente no
existe (404 en el borde). Los estados operativos (kill switch, orquestador
apagado) viajan como dict {"error": ...} — contrato histórico del frontend.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class OrchestratorServicePort(Protocol):
    """Cerebro de ejecución y conversación, agnóstico del transporte."""

    async def ejecutar_tarea(
        self, agente_id: str, tarea: str,
        datos_extra: str | None = None, archivo_id: str | None = None,
    ) -> dict:
        """Ejecuta una tarea en un agente, con telemetría y persistencia."""
        ...

    async def chat(
        self, mensaje: str, agente_id: str | None = None,
        archivo_id: str | None = None, sesion_id: str = "default",
    ) -> dict:
        """Chat con tool-calling; el orquestador elige agente si no se indica."""
        ...

    def chat_stream(
        self, mensaje: str, agente_id: str | None = None,
        archivo_id: str | None = None, sesion_id: str = "default",
    ) -> AsyncIterator[dict]:
        """Chat streaming: genera eventos dict (inicio/chunk/error/fin)."""
        ...

    async def comando_remoto(self, comando: str) -> str:
        """Comandos de control remoto ya autenticados (status, reiniciar...)."""
        ...
