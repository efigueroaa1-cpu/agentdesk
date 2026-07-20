"""
core/api/telemetry_router.py — Telemetría industrial en tiempo real y
comando/control OT (Human-in-the-loop).

Concentra el streaming de datos de planta (WS /ws/telemetria) y los
endpoints que correlacionan esa telemetría con el negocio (Gemelo Digital,
ADR-0021) y con la actuación sobre la planta (ADR-0024). El acceso a la
fuente de datos sigue el TelemetryPort agnóstico (ADR-0001) — este router
nunca importa un adaptador concreto (Modbus/MQTT/OPC-UA), solo consume los
servicios ya conectados en core/api/__init__.py::startup().

Extraído de core/api/__init__.py y core/api/monitor_router.py (organización
por dominio; ninguno de los dos superaba el límite de 500 líneas — este
split agrupa "industrial/OT" como dominio propio, no corrige una violación).
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.requests import Request

import core.api._state as _state
from core.api._state import manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Streaming en tiempo real ───────────────────────────────────────────────────

@router.websocket("/ws/telemetria")
async def websocket_telemetria(ws: WebSocket) -> None:
    """
    Endpoint WebSocket. El dashboard React conecta aquí para recibir:
      - eventos de telemetría (@measure_latency) de los filtros del pipeline
      - notificaciones de agente_creado
      - cualquier mensaje que el servidor quiera enviar en tiempo real

    Protocolo: el cliente puede enviar {"ping": true} para keepalive.
    Autenticación: JWT en query param ?token=<jwt>  (browser WS no permite headers).
    El rol del token determina qué mensajes recibe el cliente (RBAC en broadcast).
    """
    from core.auth import verificar_token as _vt
    token   = ws.query_params.get("token", "")
    payload = _vt(token) if token else None
    rol     = (payload or {}).get("role", "viewer")

    await manager.connect(ws, rol=rol)
    await ws.send_text(json.dumps({
        "tipo":    "conexion",
        "mensaje": "Conectado al servidor de telemetria AgentDesk.",
        "rol":     rol,
    }))

    try:
        while True:
            data = await ws.receive_text()
            # Responder a pings para mantener la conexion viva
            try:
                msg = json.loads(data)
                if msg.get("ping"):
                    await ws.send_text(json.dumps({"pong": True}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ── Gemelo Digital Operativo (Fase 23, ADR-0021) ──────────────────────────────

@router.get("/analytics/proyeccion-ot/{proyecto_id}")
async def analytics_proyeccion_ot(proyecto_id: str, req: Request) -> dict:
    """
    Curva S ajustada por telemetría REAL de planta: nueva fecha fin
    proyectada, impacto en cronograma y riesgo de presupuesto. Emite la
    alerta al dashboard (WS, supervisor+) si hay riesgo financiero.
    """
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")

    from core.analytics import motor_correlacion
    resultado = await asyncio.get_running_loop().run_in_executor(
        None, lambda: motor_correlacion.proyeccion_ajustada(proyecto_id))

    if resultado.get("riesgo_presupuesto") or resultado.get("impacto_cronograma"):
        await manager.broadcast(
            {
                "tipo":        "riesgo_ot_alerta",
                "proyecto_id": proyecto_id,
                "titulo":      f"Riesgo industrial-financiero en {proyecto_id}",
                "cuerpo": (
                    f"Factor de produccion={resultado['produccion']['factor']:.2f} · "
                    f"atraso proyectado={resultado['dias_atraso_proyectados']} dias · "
                    f"EAC ajustado={resultado['eac_ajustado']:.0f}"
                ),
                "riesgo_presupuesto": resultado.get("riesgo_presupuesto", False),
            },
            rol_minimo="supervisor",
        )
    return resultado


@router.get("/analytics/roi")
async def analytics_roi(req: Request, proyecto_id: str = "", dias: int = 30) -> dict:
    """
    Dashboard Ejecutivo "Real-Time ROI" (ADR-0021): costo de ejecución
    acumulado (tokens/USD de IA + carga de recursos del host) vs. el valor
    del avance físico reportado por los sensores (EV de la Curva S escalado
    por el factor de producción real).
    """
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")

    from core.services import audit_service
    from core.services.resource_guard import carga_actual

    costos = await asyncio.get_running_loop().run_in_executor(
        None, lambda: audit_service.resumen_costos(limit_dias=dias))

    valor_fisico = None
    if proyecto_id:
        from core.analytics import motor_correlacion
        p       = await asyncio.get_running_loop().run_in_executor(
            None, lambda: motor_correlacion.proyeccion_ajustada(proyecto_id))
        kpis    = p.get("curva_s", {}).get("kpis", {})
        factor  = p.get("produccion", {}).get("factor", 1.0)
        ev      = kpis.get("ev", 0) or 0
        valor_fisico = {
            "proyecto_id":        proyecto_id,
            "ev_reportado_usd":   ev,
            "factor_produccion":  factor,
            "ev_fisico_usd":      round(ev * factor, 2),
            "riesgo_presupuesto": p.get("riesgo_presupuesto", False),
            "dias_atraso_proyectados": p.get("dias_atraso_proyectados", 0),
        }

    costo_ia = costos.get("costo_usd_total", 0.0)
    tokens   = sum(d.get("tokens", 0) for d in costos.get("por_agente", {}).values())
    roi = None
    if valor_fisico and costo_ia > 0:
        roi = round(valor_fisico["ev_fisico_usd"] / costo_ia, 2)

    return {
        "ventana_dias":    dias,
        "costo_ejecucion": {"costo_ia_usd": costo_ia, "tokens": tokens,
                            "recursos_host": carga_actual()},
        "valor_fisico":    valor_fisico,
        "roi":             roi,
    }


@router.post("/analytics/riesgo-ot/{proyecto_id}")
async def analytics_riesgo_ot(proyecto_id: str, req: Request,
                              analista_id: str = "") -> dict:
    """
    Analista de Riesgos (ADR-0021): screening determinista de las últimas
    1000 métricas industriales + evaluación paralela Map-Reduce si se
    indica un agente analista. Supervisor+ (puede disparar N llamadas LLM).
    """
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")
    user_id = getattr(req.state, "user_id", "anonimo")
    return await _state._risk_service.analizar(
        proyecto_id, analista_id=analista_id or None, user_id=user_id)


# ── Comando y Control OT — Human-in-the-loop (Fase 26, ADR-0024) ──────────────

@router.get("/ot/acciones")
async def ot_acciones(req: Request, estado: str = "") -> dict:
    """
    Bandeja de propuestas de comando OT (ADR-0024). Supervisor+ — es la
    vista de aprobacion Human-in-the-loop del dashboard.
    """
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")
    from core.services.ot_command_service import ot_service
    return {"acciones": ot_service.listar(estado or None),
            "adaptadores": ot_service.adaptadores()}


@router.post("/ot/acciones/{propuesta_id}/aprobar")
async def ot_aprobar(propuesta_id: int, req: Request) -> dict:
    """
    Confirmacion de Operador (Human-in-the-loop, ADR-0024): ejecuta el
    comando propuesto. Supervisor+ OBLIGATORIO — este es el punto exacto
    donde un humano autoriza la escritura hacia la planta.
    """
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")
    from core.services.ot_command_service import ot_service
    user_id = getattr(req.state, "user_id", "anonimo")
    resultado = ot_service.aprobar(propuesta_id, user_id=user_id)
    if not resultado["ok"] and "propuesta" not in resultado:
        raise HTTPException(400, detail=resultado["detalle"])
    return resultado


@router.post("/ot/acciones/{propuesta_id}/rechazar")
async def ot_rechazar(propuesta_id: int, req: Request, motivo: str = "") -> dict:
    """Rechazo explicito del operador (queda auditado). Supervisor+."""
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")
    from core.services.ot_command_service import ot_service
    user_id = getattr(req.state, "user_id", "anonimo")
    resultado = ot_service.rechazar(propuesta_id, user_id=user_id, motivo=motivo)
    if not resultado["ok"]:
        raise HTTPException(400, detail=resultado["detalle"])
    return resultado
