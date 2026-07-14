"""
core/services/agent_service.py — Servicio de Gestión de Agentes.

Lógica de negocio extraída de core/api.py (Strangler Fig, ADR-0002): la API
valida el transporte y delega aquí. Las dependencias de runtime llegan
inyectadas como callables para respetar la dirección de dependencias:
  get_orquestador / get_bridge — leen los globals del proceso (api los cablea)
  broadcast — corrutina de difusión WebSocket (ConnectionManager de la api)

El comportamiento es idéntico al histórico: kill switch y orquestador ausente
responden {"error": ...}; agente inexistente lanza LookupError (404 en el
borde); actualización inválida lanza ValueError (400 en el borde).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from core import kill_switch
from core.command_bridge import Command, CREAR_AGENTE, RELOAD_CONFIG
from core.config_loader import load_config
from core.schemas import AgentConfig

logger = logging.getLogger(__name__)


class AgentService:
    """Implementación de core.ports.agent_port.AgentServicePort."""

    def __init__(
        self,
        get_orquestador: Callable[[], Any],
        get_bridge: Callable[[], Any],
        broadcast: Callable[[dict], Awaitable[None]],
    ):
        self._get_orquestador = get_orquestador
        self._get_bridge      = get_bridge
        self._broadcast       = broadcast

    # ── Lectura ───────────────────────────────────────────────────────────

    def listar(self) -> dict:
        """Lista agentes aplanando ubicacion.lat/lng al nivel raíz para el mapa React."""
        try:
            config  = load_config()
            agentes = []
            for a in config.get("agents", []):
                ub = a.get("ubicacion") or {}
                agentes.append({
                    **a,
                    "lat":   ub.get("lat",   a.get("lat",   0)),
                    "lng":   ub.get("lng",   a.get("lng",   0)),
                    "label": ub.get("label", a.get("label", "")),
                })
            return {"agentes": agentes}
        except Exception as e:
            return {"error": str(e), "agentes": []}

    # ── Ciclo de vida ─────────────────────────────────────────────────────

    async def crear(self, datos: dict) -> dict:
        """Valida con AgentConfig (Pydantic) y encola CREAR_AGENTE en el bridge."""
        if not kill_switch.is_active():
            return {
                "error": "Kill switch activo — creación de agentes bloqueada.",
                "kill_switch": kill_switch.estado_dict(),
            }
        bridge = self._get_bridge()
        if bridge is None:
            return {"error": "CommandBridge no disponible. El orquestador no está conectado."}

        # Validar con el mismo schema que usa el Orquestador
        try:
            AgentConfig.model_validate(datos)
        except Exception as e:
            return {"error": f"Validacion fallida: {e}"}

        await bridge.send(Command(tipo=CREAR_AGENTE, payload=dict(datos)))
        await self._broadcast({
            "tipo":   "agente_creado",
            "nombre": datos.get("nombre", ""),
            "area":   datos.get("area", ""),
        })
        return {"ok": True, "nombre": datos.get("nombre", ""), "area": datos.get("area", "")}

    async def actualizar(self, agente_id: str, cambios: dict) -> dict:
        """Actualiza parámetros de un agente en caliente. ValueError si falla."""
        if not kill_switch.is_active():
            return {"error": "Kill switch activo."}
        orq = self._get_orquestador()
        if orq is None:
            return {"error": "Orquestador no disponible."}
        ok = await orq.actualizar_agente(agente_id, cambios)
        if not ok:
            raise ValueError(f"Actualización fallida para '{agente_id}'.")
        await self._broadcast({"tipo": "agente_actualizado", "agente_id": agente_id})
        return {"ok": True, "agente_id": agente_id}

    async def eliminar(self, agente_id: str) -> dict:
        """Elimina un agente del sistema y de config.json. LookupError si no existe."""
        if not kill_switch.is_active():
            return {"error": "Kill switch activo."}
        orq = self._get_orquestador()
        if orq is None:
            return {"error": "Orquestador no disponible."}
        ok = await orq.eliminar_agente(agente_id)
        if not ok:
            raise LookupError(f"Agente '{agente_id}' no encontrado.")
        await self._broadcast({"tipo": "agente_eliminado", "agente_id": agente_id})
        return {"ok": True, "agente_id": agente_id}

    async def recargar(self, agente_id: str | None) -> dict:
        """Encola RELOAD_CONFIG; el Orquestador re-lee config.json con rollback implícito."""
        if not kill_switch.is_active():
            return {
                "error": "Kill switch activo — operación bloqueada.",
                "kill_switch": kill_switch.estado_dict(),
            }
        bridge = self._get_bridge()
        if bridge is None:
            return {"error": "CommandBridge no disponible. El orquestador no está conectado."}

        await bridge.send(Command(tipo=RELOAD_CONFIG, payload={"agente_id": agente_id}))
        await self._broadcast({
            "tipo":      "reload_solicitado",
            "agente_id": agente_id or "todos",
        })
        return {
            "ok":        True,
            "agente_id": agente_id or "todos",
            "mensaje":   "RELOAD_CONFIG encolado. El Orquestador aplicará los cambios en breve.",
        }

    async def ejecutar_todos(self) -> dict:
        """Ejecuta realizar_tarea() en TODOS los agentes en paralelo (asyncio.gather)."""
        if not kill_switch.is_active():
            return {"error": "Kill switch activo."}
        orq = self._get_orquestador()
        if orq is None:
            return {"error": "Orquestador no disponible."}

        await self._broadcast({"tipo": "todos_ejecutando",
                               "agentes": list(orq.agentes.keys())})

        resultados = {}
        tareas     = [agente.realizar_tarea("reporte_ventas") for agente in orq.agentes.values()]
        respuestas = await asyncio.gather(*tareas, return_exceptions=True)
        for aid, resp in zip(orq.agentes.keys(), respuestas):
            if isinstance(resp, Exception):
                resultados[aid] = {"ok": False, "error": str(resp)}
            else:
                ok = resp is not None
                resultados[aid] = {"ok": ok, "resumen": (resp or {}).get("resumen", "")[:150] if ok else None}

        await self._broadcast({"tipo": "todos_completados", "resultados": resultados})
        return {"ok": True, "resultados": resultados}
