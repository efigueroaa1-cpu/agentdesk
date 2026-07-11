"""
CommandBridge: canal de mensajes entre la UI y el Orquestador.

Usa asyncio.Queue para garantizar seguridad de hilos: cualquier contexto
(síncrono o asíncrono) puede encolar comandos sin interrumpir el event loop.

Uso típico:
    # desde código async (UI, menú)
    await bridge.send(Command(tipo=RELOAD_CONFIG, payload={"agente_id": "agente_bd_01"}))

    # desde código síncrono o un hilo externo
    bridge.send_sync(Command(tipo=RELOAD_CONFIG, ...), loop=loop)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# ── Tipos de comando disponibles ──────────────────────────────────────────────
RELOAD_CONFIG     = "RELOAD_CONFIG"
CREAR_AGENTE      = "CREAR_AGENTE"
ELIMINAR_AGENTE   = "ELIMINAR_AGENTE"
ACTUALIZAR_AGENTE = "ACTUALIZAR_AGENTE"
RELOAD_FINANZAS   = "RELOAD_FINANZAS"   # recarga presupuesto de un agente sin interrumpir tareas


@dataclass
class Command:
    """Mensaje enviado a través del CommandBridge."""
    tipo:    str
    payload: dict = field(default_factory=dict)


# ── Bridge principal ───────────────────────────────────────────────────────────

class CommandBridge:
    """
    Cola de mensajes async entre la UI y el Orquestador.

    Parámetros
    ----------
    maxsize : tamaño máximo de la cola (0 = ilimitada)
    """

    def __init__(self, maxsize: int = 100) -> None:
        self._queue: asyncio.Queue[Command] = asyncio.Queue(maxsize=maxsize)

    async def send(self, command: Command) -> None:
        """
        Encola un comando desde un contexto async.
        Bloquea si la cola está llena (backpressure natural).
        """
        await self._queue.put(command)
        logger.info(
            "Comando encolado",
            extra={"tipo": command.tipo, "payload": command.payload},
        )

    def send_sync(
        self,
        command: Command,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """
        Encola un comando desde un hilo síncrono externo.
        Usa call_soon_threadsafe para no bloquear el event loop.
        """
        loop.call_soon_threadsafe(self._queue.put_nowait, command)
        logger.info(
            "Comando encolado (sync)",
            extra={"tipo": command.tipo, "payload": command.payload},
        )

    async def consume(self) -> AsyncGenerator[Command, None]:
        """
        Generador async: yields comandos en orden FIFO de forma indefinida.
        La tarea que llama a este generador debe capturar asyncio.CancelledError
        para cerrarse limpiamente al salir del programa.
        """
        while True:
            cmd = await self._queue.get()
            yield cmd
            self._queue.task_done()
