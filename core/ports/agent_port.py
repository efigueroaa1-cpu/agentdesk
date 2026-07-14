"""
core/ports/agent_port.py — Puerto de Gestión de Agentes.

AgentServicePort: lo que los adaptadores de entrada (API HTTP) necesitan para
gestionar el ciclo de vida de los agentes. Implementado por
core/services/agent_service.py, que orquesta kill switch, CommandBridge y
config.json sin que la API conozca esos detalles.

Errores contractuales: `eliminar` lanza LookupError si el agente no existe
(404 en el borde); `actualizar` lanza ValueError si la actualización es
inválida (400 en el borde). Los estados operativos (kill switch activo,
orquestador ausente) se devuelven como dict {"error": ...} — contrato
histórico del frontend.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentServicePort(Protocol):
    """Gestión del ciclo de vida de agentes, agnóstica del transporte."""

    def listar(self) -> dict:
        """Agentes de config.json con ubicación aplanada (lat/lng/label)."""
        ...

    async def crear(self, datos: dict) -> dict:
        """Valida contra AgentConfig y encola CREAR_AGENTE en el bridge."""
        ...

    async def actualizar(self, agente_id: str, cambios: dict) -> dict:
        """Aplica cambios en caliente vía orquestador. ValueError si falla."""
        ...

    async def eliminar(self, agente_id: str) -> dict:
        """Elimina del sistema y de config.json. LookupError si no existe."""
        ...

    async def recargar(self, agente_id: str | None) -> dict:
        """Encola RELOAD_CONFIG (un agente o todos)."""
        ...

    async def ejecutar_todos(self) -> dict:
        """Ejecuta la tarea por defecto en todos los agentes en paralelo."""
        ...
