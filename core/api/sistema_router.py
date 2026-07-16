"""
core/api/sistema_router.py — Endpoints de operación del sistema: salud,
versión, actualizaciones, backup/restore, diagnóstico (circuit breakers,
tracing OTEL), métricas Prometheus, kill switch, logs y embeddings.

Extraído de core/api.py (Fase 17, ADR-0015).
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, UploadFile, File as _File
from fastapi.responses import Response as _Response
from starlette.requests import Request

from core.timeutil import utcnow
from core import kill_switch
import core.api._state as _state
from core.api.schemas import KillSwitchToggleRequest, KillSwitchURLRequest, UpdateURLRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/logs")
async def get_logs(n: int = 100, nivel: str = "all") -> dict:
    """Devuelve las últimas N entradas del log sistema.log como JSON."""
    return _state._analytics.leer_logs(n=n, nivel=nivel)


@router.get("/version")
async def get_version() -> dict:
    """Versión actual de AgentDesk."""
    from core.backup import _version
    return {"version": _version(), "app": "AgentDesk"}


@router.get("/update/check")
async def update_check(url: str = "") -> dict:
    """Verifica si hay una nueva versión disponible."""
    from core.updater import verificar_actualizacion
    return verificar_actualizacion(url or None)


@router.put("/update/url")
async def update_set_url(payload: UpdateURLRequest) -> dict:
    """Configura la URL del servidor de actualizaciones."""
    from core.updater import guardar_url_update
    ok = guardar_url_update(payload.url)
    return {"ok": ok, "url": payload.url}


@router.get("/backup/descargar")
async def backup_descargar(req: Request) -> _Response:
    """Genera y descarga un ZIP con toda la base de datos y configuración. Solo admin (JWT)."""
    from core.api.auth_router import exigir_admin_auditado
    exigir_admin_auditado(req, "descarga de backup", "GET /backup/descargar", logger)
    from core.backup import crear_backup
    try:
        data = await _state._queue.ejecutar_pesado(crear_backup)
        ts   = utcnow().strftime("%Y%m%d_%H%M")
        return _Response(
            content    = data,
            media_type = "application/zip",
            headers    = {"Content-Disposition": f'attachment; filename="agentdesk_backup_{ts}.zip"'},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al crear backup: {exc}")


@router.post("/backup/restaurar")
async def backup_restaurar(req: Request, archivo: UploadFile = _File(...)) -> dict:
    """Restaura un backup desde un ZIP previamente generado. Solo admin (JWT)."""
    from core.api.auth_router import exigir_admin_auditado
    exigir_admin_auditado(req, "restauracion de backup", "POST /backup/restaurar", logger)
    from core.backup import restaurar_backup
    try:
        data = await archivo.read()
        r    = restaurar_backup(data)
        if r["ok"]:
            await _state.manager.broadcast({"tipo": "backup_restaurado", "total": r["total"]})
        return r
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/rate-limiter/stats")
async def rate_limiter_stats() -> dict:
    """Estadísticas de uso del rate limiter por proveedor."""
    try:
        from core.rate_limiter import get_stats_todos
        return {"stats": get_stats_todos()}
    except Exception as exc:
        return {"stats": [], "error": str(exc)}


# ── Diagnóstico y Auditoría IA (ADR-0007/0014) ────────────────────────────────

@router.get("/diagnostico/llm")
async def diagnostico_llm() -> dict:
    """Estado OPEN/CLOSED de los Circuit Breakers y latencias por proveedor."""
    from core.services.llm_service import llm_service
    return {"circuitos": llm_service.estado_circuitos(),
            "cadena": [p for p, _ in llm_service._cadena]}


@router.get("/diagnostico/tracing")
async def diagnostico_tracing(limit: int = 100) -> dict:
    """Últimos spans OTEL capturados en memoria (ADR-0014) — sin depender de un Collector."""
    from core.telemetry_otel import spans_recientes
    return {"spans": spans_recientes(limit)}


@router.get("/diagnostico/arranque")
async def diagnostico_arranque(req: Request) -> dict:
    """
    Diagnóstico de Arranque Enterprise (ADR-0016), re-evaluado en vivo.

    Si el sistema está corriendo, ya pasó el chequeo Fail-Hard de main.py
    (criticos == [] en el momento del arranque) — esto expone la foto
    ACTUAL para que la UI muestre modo_configuracion/avisos sin tener que
    leer el log del proceso. Revela solo mensajes y booleanos, nunca los
    valores de los secretos evaluados. Requiere rol supervisor o admin,
    igual que /auditoria/* — es información sobre la postura de seguridad
    del sistema, no debe ser pública.
    """
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")
    from core.services.boot_diagnostics_service import diagnostico_arranque_sistema
    return diagnostico_arranque_sistema()


@router.get("/metrics")
async def metricas_prometheus():
    """Métricas en formato Prometheus (ADR-0014): interacciones, tokens, duración, circuitos LLM."""
    from fastapi import Response
    from core.metrics_prometheus import actualizar_circuitos_llm, generar_exposicion
    from core.services.llm_service import llm_service
    actualizar_circuitos_llm(llm_service.estado_circuitos())
    payload, content_type = generar_exposicion()
    return Response(content=payload, media_type=content_type)


@router.get("/auditoria/interacciones")
async def auditoria_interacciones(req: Request, agente_id: str = "",
                                  user_id: str = "", limit: int = 50) -> dict:
    """Trazas forenses de interacciones IA. Requiere rol supervisor o admin."""
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")
    from core.services import audit_service
    return {"interacciones": audit_service.consultar(
        agente_id or None, user_id or None, limit)}


@router.get("/auditoria/costos")
async def auditoria_costos(req: Request, dias: int = 30) -> dict:
    """Tokens estimados por agente (ventana N días). Supervisor o admin."""
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")
    from core.services import audit_service
    return audit_service.resumen_costos(dias)


@router.get("/health")
async def health() -> dict:
    agentes_info = {}
    if _state._orquestador:
        for aid, ag in _state._orquestador.agentes.items():
            agentes_info[aid] = {
                "nombre":  ag.nombre,
                "modelo":  ag.modelo,
                "area":    getattr(ag, "area", "General"),
                "status":  "idle",
            }
    return {
        "status":    "ok",
        "clientes_ws": len(_state.manager.active),
        "agentes":   agentes_info,
    }


@router.get("/embeddings")
async def get_embeddings() -> dict:
    """
    Embeddings semánticos reales usando TF-IDF + PCA.
    Los agentes similares (mismo dominio, mismos temas) quedan CERCANOS en 3D.
    """
    return await _state._queue.ejecutar_pesado(_state._analytics.embeddings_3d, _state._orquestador)


@router.get("/kill-switch")
async def estado_kill_switch() -> dict:
    """
    Retorna el estado actual del kill switch (incluye gist_url para la UI).
    El monitor de background actualiza el estado cada 5 minutos.
    """
    return kill_switch.estado_dict()


@router.post("/kill-switch/toggle")
async def toggle_kill_switch(payload: KillSwitchToggleRequest) -> dict:
    """
    Activa o bloquea el Kill Switch manualmente desde el SecurityPanel.
    Requiere rol admin (verificado por JWTMiddleware).
    El monitor del Gist puede sobreescribir este estado en la siguiente verificación.
    """
    kill_switch.forzar_estado(payload.activo)
    logger.info("Kill switch toggled a %s via API.", payload.activo)
    return kill_switch.estado_dict()


@router.post("/kill-switch/url")
async def configurar_kill_switch_url(payload: KillSwitchURLRequest) -> dict:
    """
    Actualiza la URL del Gist de Kill Switch en tiempo de ejecucion.
    Requiere JWT con rol admin (protegido por JWTMiddleware).
    Si url es vacia, desactiva el control remoto.
    """
    kill_switch.set_gist_url(payload.url)
    if payload.url:
        resultado = await kill_switch.verificar_gist()
        return {"ok": True, "url": payload.url, "active": resultado}
    return {"ok": True, "url": "", "active": True, "nota": "Control remoto desactivado."}


@router.get("/sistema/salud")
async def sistema_salud() -> dict:
    """
    KPIs maestros consolidados: Gantt + Finanzas + Compliance + Riesgo.
    Score 0-100 ponderado para el Central Control Panel (BIDashboard ID 9).
    """
    from core.risk_engine import motor_riesgo
    return motor_riesgo.salud_sistema()


@router.get("/docs/manual")
async def descargar_manual(empresa: str = "AgentDesk") -> _Response:
    """
    Genera y descarga el Manual de Usuario en PDF personalizado con el nombre de la empresa.
    Ejemplo: GET /docs/manual?empresa=ACME+S.A.
    """
    import asyncio
    from core.docs_gen import generar_manual
    loop      = asyncio.get_running_loop()
    pdf_bytes = await loop.run_in_executor(None, lambda: generar_manual(empresa))
    nombre    = f"Manual_AgentDesk_{empresa.replace(' ', '_')}.pdf"
    return _Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
