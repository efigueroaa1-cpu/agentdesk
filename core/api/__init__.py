"""
core/api — Servidor FastAPI para el dashboard React de AgentDesk.

Paquete (Fase 17, ADR-0015): antes era un único core/api.py de 1552 líneas;
ahora es la raíz de composición (app, middlewares, estado compartido, eventos
de ciclo de vida, WS /ws/telemetria) que registra un router por dominio:

  core/api/_state.py          Estado compartido y servicios (sin FastAPI routes)
  core/api/schemas.py         Modelos Pydantic de request compartidos
  core/api/auth_router.py     /auth/*                  (ADR-0002, sin cambios)
  core/api/agentes_router.py  /agentes/*, /chat*, /memoria/*, /uploads, /proveedores
  core/api/sistema_router.py  /health, /version, /backup/*, /diagnostico/*, /metrics, /kill-switch*
  core/api/monitor_router.py  /monitor/*, /scheduler/*, /dashboard/*, /alertas/*, /pipeline/config
  core/api/reportes_router.py /reportes/*, /generar-pdf, /gantt/*, /finanzas/*, /webhook/whatsapp

Expone (igual que antes del split):
  WS  /ws/telemetria         Emite eventos de telemetria (@measure_latency) en tiempo real.
  POST /agentes              Crea un nuevo agente (envia CREAR_AGENTE al CommandBridge).
  GET  /agentes              Lista los agentes actuales.
  GET  /health               Verifica que el servidor este activo.
  GET  /kill-switch          Estado del kill switch remoto (Gist de GitHub).
  POST /reload               Recarga la config de uno o todos los agentes (RELOAD_CONFIG).

Arranque autónomo (sin main.py):
  python -m uvicorn core.api:app --host 0.0.0.0 --port 8000 --reload

El servidor inicializa el Orquestador en el evento startup si GEMINI_API_KEY
está configurada. También acepta un bridge externo via registrar_bridge()
para el modo combinado CLI+API.

El dashboard React conecta a ws://localhost:8000/ws/telemetria
y recibe los mismos eventos JSON que el FilterLogHandler envía al terminal.

Contrato de import preservado: `from core.api import app`, `from core.api
import manager`, `from core.api import registrar_bridge, registrar_orquestador`
siguen funcionando idéntico a como funcionaban con el core/api.py de un solo
archivo (main.py, test_security.py y varios tests dependen de esto).
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.path_manager import resource_path
from core import kill_switch

import core.api._state as _state
from core.api._state import (  # re-export: contrato de import preservado
    ConnectionManager,
    manager,
    registrar_bridge,
    registrar_orquestador,
    instalar_ws_handler,
)

logger = logging.getLogger(__name__)

# ── Instancia FastAPI ──────────────────────────────────────────────────────────
app = FastAPI(title="AgentDesk API", version="1.0.0")

# CORS restrictivo: solo localhost (la app es local, no expuesta a internet)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://localhost:5173",   # Vite dev server
        "http://localhost:3000",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    allow_credentials=True,
)

# ── Middleware JWT + routers de dominio ─────────────────────────────────────────
from core.api.auth_router import JWTMiddleware, router as _auth_router
from core.api.agentes_router import router as _agentes_router
from core.api.sistema_router import router as _sistema_router
from core.api.monitor_router import router as _monitor_router
from core.api.reportes_router import router as _reportes_router

app.add_middleware(JWTMiddleware)
app.include_router(_auth_router)
app.include_router(_agentes_router)
app.include_router(_sistema_router)
app.include_router(_monitor_router)
app.include_router(_reportes_router)

# ── React UI estático en /ui/ ──────────────────────────────────────────────────
# Servido íntegramente por StaticFiles; el middleware inferior fuerza no-cache
# en todo /ui/* (evita el cache agresivo de WebView2 tras cada build).
_react_dist = resource_path("react_dist")

@app.middleware("http")
async def _no_cache_ui(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/ui/") or request.url.path == "/ui":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

if _react_dist.exists():
    app.mount("/ui", StaticFiles(directory=str(_react_dist), html=True), name="ui")


@app.on_event("startup")
async def startup() -> None:
    instalar_ws_handler()

    # Inicializar SQLite
    try:
        from core.database import init_db
        init_db()
        logger.info("SQLite inicializado correctamente")
    except Exception as exc:
        logger.error("SQLite init error: %s", exc)

    # Migrar API keys al vault cifrado (primera vez)
    try:
        from core.key_vault import migrar_env_a_vault
        r = migrar_env_a_vault()
        if r["migradas"]:
            logger.info("Vault: %d API keys migradas", r["migradas"])
    except Exception as exc:
        logger.warning("Vault migration: %s", exc)

    # Inicializar Scheduler de Monitoreo Automático
    try:
        from core.scheduler import start_scheduler
        start_scheduler(
            orquestador=_state._orquestador,
            broadcast=manager.broadcast,
        )
        logger.info("Scheduler de monitoreo iniciado")
    except Exception as exc:
        logger.error("Scheduler init error: %s", exc)

    # React /ui/ montado a nivel de módulo (no aquí) para correcta compilación de rutas Starlette

    # Kill switch: arrancar monitor de verificación periódica
    _state._tarea_monitor = asyncio.create_task(kill_switch.iniciar_monitor())

    # Verificación inmediata (no espera el primer intervalo de 5 min)
    await kill_switch.verificar_gist()

    # Alertas activas de SLOs industriales (Fase 20, ADR-0018)
    try:
        from core.services.alert_service import iniciar_monitor as _iniciar_monitor_alertas
        _state._tarea_alertas = asyncio.create_task(_iniciar_monitor_alertas())
        logger.info("Alert service (SLOs) iniciado")
    except Exception as exc:
        logger.error("Alert service init error: %s", exc)

    # Higiene de datos: purga/anonimización periódica por retención (Fase 20, ADR-0018)
    try:
        from core.services.audit_service import iniciar_monitor_purga as _iniciar_monitor_purga
        _state._tarea_purga = asyncio.create_task(_iniciar_monitor_purga())
        logger.info("Purga de retención de auditoría iniciada")
    except Exception as exc:
        logger.error("Purge service init error: %s", exc)

    # Auto-inicializar Orquestador si no hay bridge externo
    await _state._auto_iniciar_orquestador()


@app.on_event("shutdown")
async def shutdown() -> None:
    for tarea in (_state._tarea_monitor, _state._tarea_cmds,
                  _state._tarea_alertas, _state._tarea_purga):
        if tarea and not tarea.done():
            tarea.cancel()
            try:
                await tarea
            except asyncio.CancelledError:
                pass


@app.websocket("/ws/telemetria")
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
