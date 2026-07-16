"""
core/api/agentes_router.py — Endpoints centrados en el ciclo de vida del
agente: CRUD, ejecución de tareas, chat (normal y streaming), memoria de
conversación, historial/tendencias, subida de archivos y proveedores/modelos.

Extraído de core/api.py (Fase 17, ADR-0015). La lógica de negocio vive en
core/services/* (agent_service, orchestrator_service, analytics_service,
upload_service, report_service) — este módulo solo traduce HTTP ⇄ servicio,
igual que el precedente ya establecido en core/api/auth_router.py.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, UploadFile, File as _File
from fastapi.responses import FileResponse, StreamingResponse as _StreamingResponse
from starlette.requests import Request

import core.api._state as _state
from core.api.schemas import (
    ActualizarAgenteRequest,
    ChatRequest,
    EjecutarRequest,
    NuevoAgenteRequest,
    ReloadRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agentes/ejecutar-todos")
async def ejecutar_todos() -> dict:
    """Ejecuta realizar_tarea() en TODOS los agentes en paralelo (agent_service)."""
    return await _state._agent_service.ejecutar_todos()


@router.post("/agentes/{agente_id}/ejecutar")
async def ejecutar_agente(agente_id: str, payload: EjecutarRequest, req: Request) -> dict:
    """
    Ejecuta realizar_tarea() en el agente especificado.
    Emite eventos de telemetría en tiempo real via WebSocket /ws/telemetria.
    Retorna el reporte final o un error detallado.
    """
    try:
        return await _state._orch_service.ejecutar_tarea(
            agente_id, payload.tarea,
            datos_extra=payload.datos_extra, archivo_id=payload.archivo_id,
            user_id=getattr(req.state, "usuario", None) or "anonimo",
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/agentes")
async def listar_agentes() -> dict:
    """Lista agentes aplanando ubicacion.lat/lng al nivel raíz para el mapa React."""
    return _state._agent_service.listar()


@router.delete("/agentes/{agente_id}")
async def eliminar_agente(agente_id: str) -> dict:
    """Elimina un agente del sistema y de config.json."""
    try:
        return await _state._agent_service.eliminar(agente_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/agentes/{agente_id}")
async def actualizar_agente(agente_id: str, payload: ActualizarAgenteRequest) -> dict:
    """Actualiza parámetros de un agente existente con validación Pydantic."""
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        return await _state._agent_service.actualizar(agente_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agentes", status_code=201)
async def crear_agente(payload: NuevoAgenteRequest) -> dict:
    """
    Valida con AgentConfig (Pydantic) y encola CREAR_AGENTE en el CommandBridge.
    El Orquestador consume el comando y persiste en config.json.
    """
    return await _state._agent_service.crear(payload.model_dump())


@router.post("/reload")
async def recargar_config(payload: ReloadRequest) -> dict:
    """
    Envía RELOAD_CONFIG al CommandBridge.

    El Orquestador re-lee config.json, valida cada agente con Pydantic
    y aplica los cambios en caliente.  Si la validación falla, el agente
    mantiene su configuración anterior (rollback implícito).

    payload.agente_id: ID del agente a recargar, o null para todos.
    """
    return await _state._agent_service.recargar(payload.agente_id)


# ── Reportes PDF por agente (lógica en report_service) ────────────────────────

@router.get("/agentes/{agente_id}/reporte")
async def descargar_reporte(agente_id: str) -> FileResponse:
    """
    Devuelve el PDF de éxito más reciente del agente como descarga directa.

    Busca en %APPDATA%\\AgentDesk\\reportes\\ archivos de la forma:
      reporte_{slug}_{YYYYMMDD}_{HHMMSS}.pdf

    Responde 404 si el agente aún no tiene reportes (no ha ejecutado el pipeline).
    """
    pdf = _state._reports.buscar_pdf("reporte", agente_id)
    if not pdf:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Sin reporte PDF para '{agente_id}'. "
                "Ejecuta el agente desde el backend Python para generarlo."
            ),
        )
    return FileResponse(
        path=str(pdf),
        media_type="application/pdf",
        filename=pdf.name,
        headers={"Content-Disposition": f'attachment; filename="{pdf.name}"'},
    )


@router.get("/agentes/{agente_id}/correccion")
async def descargar_correccion(agente_id: str) -> FileResponse:
    """Devuelve el PDF de corrección más reciente del agente."""
    pdf = _state._reports.buscar_pdf("correccion", agente_id)
    if not pdf:
        raise HTTPException(
            status_code=404,
            detail=f"Sin PDF de corrección para '{agente_id}'.",
        )
    return FileResponse(
        path=str(pdf),
        media_type="application/pdf",
        filename=pdf.name,
        headers={"Content-Disposition": f'attachment; filename="{pdf.name}"'},
    )


@router.get("/agentes/{agente_id}/reportes")
async def listar_reportes(agente_id: str) -> dict:
    """
    Lista todos los PDFs disponibles para el agente (éxito + correcciones).
    Ordenados por fecha descendente.
    """
    return _state._reports.listar_por_agente(agente_id)


# ── Historial / tendencias ─────────────────────────────────────────────────────

@router.get("/historial/agente/{agente_id}")
async def historial_agente(agente_id: str, limit: int = 50) -> dict:
    """Historial real de ejecuciones de un agente desde SQLite."""
    from core.database import get_historial, get_stats_agente
    return {
        "historial": get_historial(agente_id=agente_id, limit=limit),
        "stats":     get_stats_agente(agente_id),
    }


@router.get("/historial")
async def historial_global(limit: int = 100) -> dict:
    """Historial global de todas las ejecuciones."""
    from core.database import get_historial
    return {"historial": get_historial(limit=limit)}


@router.get("/tendencias/{agente_id}")
async def tendencias_agente(agente_id: str, dias: int = 30) -> dict:
    """Tendencias de rendimiento del agente (regresion lineal, analytics_service)."""
    return await _state._analytics.tendencias_agente(agente_id, dias=dias)


@router.get("/agentes-stats")
async def agentes_stats_all() -> dict:
    """Estadisticas historicas de todos los agentes (formato localStorage v2)."""
    return await _state._analytics.agentes_stats(dias=90)


# ── Chat libre con agentes ─────────────────────────────────────────────────────

@router.post("/chat")
async def chat(payload: ChatRequest, req: Request) -> dict:
    """Envía un mensaje conversacional a un agente. El orquestador elige el agente si no se especifica."""
    return await _state._orch_service.chat(
        payload.mensaje, agente_id=payload.agente_id,
        archivo_id=payload.archivo_id, sesion_id=payload.sesion_id,
        user_id=getattr(req.state, "usuario", None) or "anonimo",
    )


@router.get("/memoria/{agente_id}/sesiones")
async def memoria_sesiones(agente_id: str) -> dict:
    """Lista las sesiones de conversación de un agente."""
    from core.memory import get_sesiones_agente
    return {"sesiones": get_sesiones_agente(agente_id)}


@router.get("/memoria/{agente_id}/historial/{sesion_id}")
async def memoria_historial(agente_id: str, sesion_id: str) -> dict:
    """Historial completo de una sesión de conversación."""
    from core.memory import get_historial_sesion
    return {"mensajes": get_historial_sesion(agente_id, sesion_id)}


@router.delete("/memoria/{agente_id}/sesion/{sesion_id}")
async def memoria_limpiar(agente_id: str, sesion_id: str) -> dict:
    """Elimina todos los mensajes de una sesión (resetear conversación)."""
    from core.memory import limpiar_sesion
    limpiar_sesion(agente_id, sesion_id)
    return {"ok": True}


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, req: Request) -> _StreamingResponse:
    """
    Versión STREAMING del chat — devuelve Server-Sent Events (SSE).
    El motor genera eventos dict (orchestrator_service); aquí solo se
    serializan a SSE — puro adaptador de transporte.
    """
    import json as _json
    _user = getattr(req.state, "usuario", None) or "anonimo"

    async def event_generator():
        async for evento in _state._orch_service.chat_stream(
            payload.mensaje, agente_id=payload.agente_id,
            archivo_id=payload.archivo_id, sesion_id=payload.sesion_id,
            user_id=_user,
        ):
            yield f"data: {_json.dumps(evento, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return _StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering":"no",
            "Connection":       "keep-alive",
        },
    )


# ── Uploads ─────────────────────────────────────────────────────────────────────

@router.get("/uploads")
async def listar_uploads() -> dict:
    """Lista todos los archivos subidos disponibles para analizar."""
    return _state._uploads.listar_uploads()


@router.get("/uploads/{archivo_id}/texto")
async def get_upload_texto(archivo_id: str) -> dict:
    """Devuelve el contenido de texto de un archivo subido."""
    try:
        return _state._uploads.texto_upload(archivo_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/upload")
async def upload_archivo(archivo: UploadFile = _File(...)) -> dict:
    """Sube un archivo para análisis. Devuelve archivo_id + preview de CSV/Excel."""
    contenido = await archivo.read()
    return _state._uploads.guardar_upload(archivo.filename or "archivo", contenido)


# ── Proveedores / modelos ────────────────────────────────────────────────────────

@router.get("/proveedores")
async def listar_proveedores() -> dict:
    """Devuelve todos los proveedores de IA disponibles y sus modelos."""
    from core.providers import modelos_disponibles, proveedores_configurados
    return {
        "proveedores":  proveedores_configurados(),
        "modelos":      modelos_disponibles(),
    }


@router.put("/proveedores/apikey")
async def guardar_api_key(payload: dict) -> dict:
    """Guarda una API key de proveedor en .env + vault (lógica en providers)."""
    proveedor = payload.get("proveedor", "").upper()
    api_key   = payload.get("api_key", "").strip()
    if not proveedor or not api_key:
        raise HTTPException(status_code=400, detail="proveedor y api_key son requeridos.")
    from core.providers import guardar_api_key as _guardar
    return _guardar(proveedor, api_key)


@router.get("/modelos")
async def listar_modelos() -> dict:
    """Devuelve todos los modelos de todos los proveedores configurados."""
    from core.providers import modelos_disponibles
    return {"modelos": modelos_disponibles()}
