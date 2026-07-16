"""
core/ports/harness_port.py — Puerto de Harness Attachments (ADR-0009).

Un HAT (Harness Attachment) es una capacidad modular atachable a un agente
por configuración (`"harnesses": ["memoria"]`). Los hooks son best-effort:
quien orquesta (HarnessService) debe capturar cualquier excepción — un HAT
roto jamás debe romper la conversación del usuario, mismo principio que
audit_service (ADR-0007).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class HarnessPort(Protocol):
    """Interfaz que implementa cada HAT (memoria, autocrítica futura, ...)."""

    nombre: str

    def attach(self, agente_id: str, config: dict) -> None:
        """Vincula el harness a un agente concreto antes de aplicarle hooks."""
        ...

    def detach(self) -> None:
        """Libera el estado atado al agente (fin de la interacción)."""
        ...

    async def apply_hooks(self, fase: str, contexto: dict) -> dict:
        """
        Ejecuta el hook de la fase indicada sobre el contexto de la
        interacción y devuelve el contexto (posiblemente enriquecido).
        Async porque un HAT puede necesitar volver a llamar al LLM (p.ej.
        CritiqueHarness regenerando una respuesta rechazada).

        fase='pre'  — antes de enviar el prompt al LLM (p.ej. inyectar
                       memoria recuperada en contexto['memoria_semantica'],
                       filtrada obligatoriamente por contexto['user_id']).
        fase='post' — después de recibir la respuesta (p.ej. autocrítica
                       corrigiendo contexto['respuesta']).
        """
        ...
