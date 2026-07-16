"""
core/api/_state.py — Estado compartido y composición de servicios del servidor.

Extraído de core/api.py (Fase 17, ADR-0015). Vive aparte de __init__.py y de
los routers a propósito, para romper la circularidad: __init__.py importa los
routers para registrarlos (app.include_router), y los routers necesitan leer
este estado (manager, _agent_service, _orquestador...) — si ese estado viviera
en __init__.py, los routers tendrían que importar el paquete que los está
importando a ellos.

Este módulo NO importa nada de __init__.py ni de los routers: es una hoja del
grafo de imports. Los routers hacen `import core.api._state as _state` y leen
SIEMPRE por atributo (`_state.manager`, `_state._orquestador`, ...) — nunca
`from core.api._state import _orquestador`, porque _orquestador/_bridge se
reasignan en caliente (registrar_bridge/registrar_orquestador) y un `from...
import` congelaría el valor None inicial en el namespace del router.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

from core.command_bridge import CommandBridge

logger = logging.getLogger(__name__)


# ── Gestor de conexiones WebSocket ────────────────────────────────────────────
class ConnectionManager:
    """
    Mantiene la lista de clientes WebSocket conectados con su rol RBAC.
    broadcast() acepta rol_minimo para filtrar destinatarios (ej. solo supervisor+).
    """

    def __init__(self) -> None:
        # ws -> rol del usuario ("viewer" | "supervisor" | "admin")
        self._clientes: dict[WebSocket, str] = {}

    @property
    def active(self) -> list[WebSocket]:
        return list(self._clientes.keys())

    async def connect(self, ws: WebSocket, rol: str = "viewer") -> None:
        await ws.accept()
        self._clientes[ws] = rol

    def disconnect(self, ws: WebSocket) -> None:
        self._clientes.pop(ws, None)

    async def broadcast(self, mensaje: dict, rol_minimo: str = "viewer") -> None:
        """
        Envía `mensaje` solo a los clientes cuyo rol >= rol_minimo.
        rol_minimo="viewer" → todos; "supervisor" → excluye viewers; "admin" → solo admins.
        """
        from core.auth import tiene_permiso
        texto   = json.dumps(mensaje, ensure_ascii=False)
        muertos: list[WebSocket] = []
        for ws, rol_cliente in list(self._clientes.items()):
            if not tiene_permiso(rol_cliente, rol_minimo):
                continue
            try:
                await ws.send_text(texto)
            except Exception:
                muertos.append(ws)
        for ws in muertos:
            self._clientes.pop(ws, None)


manager = ConnectionManager()

# ── Estado interno del servidor ───────────────────────────────────────────────
# _bridge        : inyectado desde main.py O auto-inicializado en startup.
# _tarea_monitor : tarea background del kill switch (cancelada en shutdown).
# _tarea_cmds    : tarea background del CommandBridge (cancelada en shutdown).
# _tarea_alertas : tarea background de alert_service (Fase 20, ADR-0018).
# _tarea_purga   : tarea background de purga de retencion (Fase 20, ADR-0018).
_bridge:        CommandBridge | None = None
_tarea_monitor: asyncio.Task | None  = None
_tarea_cmds:    asyncio.Task | None  = None
_tarea_alertas: asyncio.Task | None  = None
_tarea_purga:   asyncio.Task | None  = None
_orquestador:   object | None        = None   # Orquestador (tipado como object para evitar import circular)

# Servicio de gestión de agentes (hexagonal): los lambdas leen los globals de
# este módulo en tiempo de llamada, así el servicio ve el bridge/orquestador
# vigentes sin importar la capa api (ADR-0002).
from core.services.agent_service import AgentService
from core.services.orchestrator_service import OrchestratorService
from core.services.pipeline_service import pipeline_service as _pipeline_service
from core.services import analytics_service as _analytics
from core.services import insights_service as _insights
from core.services import upload_service as _uploads
from core.services import report_service as _reports
from core.services.queue_service import queue_service as _queue

_agent_service = AgentService(
    get_orquestador=lambda: _orquestador,
    get_bridge=lambda: _bridge,
    broadcast=lambda msg: manager.broadcast(msg),
)
_orch_service = OrchestratorService(
    get_orquestador=lambda: _orquestador,
    get_bridge=lambda: _bridge,
    broadcast=lambda msg: manager.broadcast(msg),
)


def registrar_bridge(bridge: CommandBridge) -> None:
    """Inyecta un CommandBridge externo (p.ej. desde main.py en modo CLI+API)."""
    global _bridge
    _bridge = bridge


def registrar_orquestador(orch: object) -> None:
    """Inyecta la referencia al Orquestador para que los endpoints puedan llamarlo."""
    global _orquestador
    _orquestador = orch


# ── Handler de logging que reenvía telemetría al WebSocket ───────────────────
class WebSocketLogHandler(logging.Handler):
    """
    Intercepta las entradas de @measure_latency (campos filtro + duracion_s)
    y las emite como eventos JSON a todos los clientes WebSocket conectados.

    Se instala en el logger core.pipeline igual que FilterLogHandler,
    pero en lugar de imprimir en terminal envía al dashboard React.
    """

    def emit(self, record: logging.LogRecord) -> None:
        filtro   = getattr(record, "filtro",     None)
        duracion = getattr(record, "duracion_s", None)
        status   = getattr(record, "status",     "")
        agente   = getattr(record, "agente",     "")

        # ── Evento de filtro ejecutado / timeout / error ───────────────────────
        if filtro and duracion is not None:
            mensaje = {
                "tipo":       "telemetria",
                "filtro":     filtro,
                "agente":     agente,
                "status":     status or "ok",
                "duracion_s": duracion,
                "timestamp":  record.created,
            }

        # ── Pipeline abortado (no tiene duracion_s pero sí motivo) ─────────────
        elif status == "abortado" and agente:
            mensaje = {
                "tipo":      "pipeline_abortado",
                "agente":    agente,
                "filtro":    filtro or "",
                "motivo":    getattr(record, "motivo", record.getMessage()),
                "nivel":     record.levelname,
                "timestamp": record.created,
            }

        else:
            return   # ignorar el resto

        # Enviar de forma async sin bloquear el logging handler.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast(mensaje))

            # Actualizar progreso Gantt cuando el pipeline termina OK
            if mensaje["tipo"] == "telemetria" and mensaje["status"] == "ok" and agente:
                loop.create_task(_actualizar_gantt_desde_telemetria(agente, mensaje))

            # Persistir abortos de guardrail en DB para compliance
            if mensaje["tipo"] == "pipeline_abortado" and agente:
                loop.create_task(_persistir_guardrail(
                    agente,
                    getattr(record, "filtro", "desconocido") or "desconocido",
                    mensaje.get("motivo", ""),
                ))
        except RuntimeError:
            pass  # sin loop activo — se descarta el evento


async def _actualizar_gantt_desde_telemetria(agente_id: str, _evento: dict) -> None:
    """
    Incrementa el progreso de las tareas Gantt del agente cuando su pipeline
    reporta un filtro exitoso. El incremento es proporcional a los filtros
    completados (cada 'ok' suma ~10% hasta el máximo de 100%).
    Los cambios se transmiten a todos los clientes WS via gantt_progreso.
    """
    try:
        from core.gantt import motor_gantt
        actualizadas = motor_gantt.actualizar_progreso_por_agente(agente_id, incremento_pct=10.0)
        for t in actualizadas:
            await manager.broadcast({
                "tipo":      "gantt_progreso",
                "tarea_id":  t["id"],
                "proyecto":  t["proyecto_id"],
                "agente_id": agente_id,
                "pct":       t["pct_completado"],
            })
    except Exception:
        pass  # nunca romper el flujo de telemetría


async def _persistir_guardrail(agente_id: str, guardrail: str, motivo: str) -> None:
    """Persiste un evento de aborto de guardrail en DB y notifica a compliance."""
    try:
        from core.compliance import motor_compliance
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: motor_compliance.registrar_evento(agente_id, guardrail, motivo),
        )
    except Exception:
        pass  # nunca romper el flujo de telemetría


def instalar_ws_handler() -> None:
    """
    Añade WebSocketLogHandler al logger de pipeline.
    Llamar una vez al arrancar el servidor.
    """
    pl = logging.getLogger("core.pipeline")
    if not any(isinstance(h, WebSocketLogHandler) for h in pl.handlers):
        pl.addHandler(WebSocketLogHandler(level=logging.DEBUG))


async def _auto_iniciar_orquestador() -> None:
    """
    Inicializa el Orquestador dentro del proceso FastAPI si aún no hay bridge
    registrado y GEMINI_API_KEY está disponible en el entorno.

    Permite que `uvicorn core.api:app` arranque como servidor autónomo
    sin necesidad de main.py, manteniendo el desacoplamiento total:
    la UI (React, CLI, cualquier cliente WS) puede conectarse o no.
    """
    import os

    global _bridge, _tarea_cmds

    if _bridge is not None:
        return  # Ya registrado externamente — no sobreescribir

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning(
            "API: GEMINI_API_KEY no disponible — "
            "Orquestador no inicializado. Los endpoints de agentes estarán inactivos."
        )
        return

    try:
        from google import genai
        from core.orchestrator import Orquestador
        from core.path_manager import resource_path

        client = genai.Client(api_key=api_key)
        pager  = await client.aio.models.list()
        model  = None
        async for m in pager:
            if "generateContent" in (m.supported_actions or []):
                model = m.name
                break

        if not model:
            logger.error("API startup: ningún modelo Gemini disponible.")
            return

        config_path = str(resource_path("config.json"))

        bridge = CommandBridge()
        orch   = Orquestador(config_path, client, model, bridge=bridge)

        registrar_bridge(bridge)
        registrar_orquestador(orch)
        from core.tools import set_orquestador
        set_orquestador(orch)   # ADR-0011: delegacion cognitiva Speak/Listen
        _tarea_cmds = asyncio.create_task(orch.procesar_comandos())

        logger.info(
            "API: Orquestador auto-inicializado.",
            extra={"modelo": model, "agentes": list(orch.agentes.keys())},
        )
    except Exception as exc:
        logger.error("API startup: fallo al inicializar Orquestador: %s", exc)
