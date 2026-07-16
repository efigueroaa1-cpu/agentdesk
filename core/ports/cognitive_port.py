"""
core/ports/cognitive_port.py — Puertos Speak/Listen (ADR-0011).

Delegación cognitiva en runtime: un agente puede pedirle ayuda a otro
agente sin salir del flujo de tool-calling en curso. Speak es el lado del
agente que emite la subtarea; Listen es el lado del agente que la recibe y
produce una respuesta. Best-effort: una delegación fallida no debe romper
la conversación del agente que delega — se degrada a un mensaje de error
legible, nunca una excepción sin capturar.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SpeakPort(Protocol):
    async def speak(self, origen_id: str, destino_id: str, mensaje: str,
                     user_id: str = "anonimo") -> str:
        """origen_id delega `mensaje` a destino_id y retorna la respuesta obtenida."""
        ...


@runtime_checkable
class ListenPort(Protocol):
    async def listen(self, destino_id: str, origen_id: str, mensaje: str,
                      user_id: str = "anonimo") -> str:
        """destino_id procesa una subtarea delegada por origen_id y responde."""
        ...
