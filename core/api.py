"""
core/api.py — Servidor FastAPI para el dashboard React de AgentDesk.

Expone:
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
"""

from __future__ import annotations

import asyncio
from core.timeutil import utcnow
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File as _File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response as _Response
from pydantic import BaseModel

from core.command_bridge import CommandBridge, Command, RELOAD_CONFIG, RELOAD_FINANZAS
from core.config_loader  import load_config
from core.path_manager   import REPORTES_DIR, resource_path
from core              import kill_switch
from fastapi.staticfiles import StaticFiles

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

# ── Middleware JWT + endpoints /auth/* (adaptador en core/api_auth.py) ─────────
from starlette.requests import Request      # alias para type hints en endpoints
from core.api_auth import JWTMiddleware, router as _auth_router

app.add_middleware(JWTMiddleware)
app.include_router(_auth_router)

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
_bridge:        CommandBridge | None = None
_tarea_monitor: asyncio.Task | None  = None
_tarea_cmds:    asyncio.Task | None  = None
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

async def _auto_iniciar_orquestador() -> None:
    """
    Inicializa el Orquestador dentro del proceso FastAPI si aún no hay bridge
    registrado y GEMINI_API_KEY está disponible en el entorno.

    Permite que `uvicorn core.api:app` arranque como servidor autónomo
    sin necesidad de main.py, manteniendo el desacoplamiento total:
    la UI (React, CLI, cualquier cliente WS) puede conectarse o no.
    """
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

        from core.path_manager import resource_path
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


@app.on_event("startup")
async def startup() -> None:
    global _tarea_monitor

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
        _task_scheduler = start_scheduler(
            orquestador=_orquestador,
            broadcast=manager.broadcast,
        )
        logger.info("Scheduler de monitoreo iniciado")
    except Exception as exc:
        logger.error("Scheduler init error: %s", exc)

    # React /ui/ montado a nivel de módulo (no aquí) para correcta compilación de rutas Starlette

    # Kill switch: arrancar monitor de verificación periódica
    _tarea_monitor = asyncio.create_task(kill_switch.iniciar_monitor())

    # Verificación inmediata (no espera el primer intervalo de 5 min)
    await kill_switch.verificar_gist()

    # Auto-inicializar Orquestador si no hay bridge externo
    await _auto_iniciar_orquestador()


@app.on_event("shutdown")
async def shutdown() -> None:
    for tarea in (_tarea_monitor, _tarea_cmds):
        if tarea and not tarea.done():
            tarea.cancel()
            try:
                await tarea
            except asyncio.CancelledError:
                pass


@app.post("/agentes/ejecutar-todos")
async def ejecutar_todos() -> dict:
    """Ejecuta realizar_tarea() en TODOS los agentes en paralelo (agent_service)."""
    return await _agent_service.ejecutar_todos()


@app.get("/logs")
async def get_logs(n: int = 100, nivel: str = "all") -> dict:
    """Devuelve las últimas N entradas del log sistema.log como JSON."""
    return _analytics.leer_logs(n=n, nivel=nivel)


@app.get("/reportes")
async def listar_todos_reportes() -> dict:
    """Lista todos los reportes PDF de todos los agentes."""
    return _reports.listar_todos()


from fastapi.responses import FileResponse as _FileResponse

@app.get("/reportes/{nombre}")
async def descargar_reporte_directo(nombre: str) -> _FileResponse:
    """Descarga un archivo de reportes por nombre."""
    try:
        archivo = _reports.ruta_reporte(nombre)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    media = "application/pdf" if archivo.suffix == ".pdf" else "text/plain"
    return _FileResponse(str(archivo), filename=nombre, media_type=media,
                         headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@app.get("/reportes/{nombre}/abrir")
async def abrir_reporte_os(nombre: str) -> dict:
    """Abre el archivo con la aplicación predeterminada del sistema operativo."""
    try:
        os.startfile(str(_reports.ruta_reporte(nombre)))
        return {"ok": True, "nombre": nombre}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al abrir archivo: {exc}")


# ── Dashboard Analytics ───────────────────────────────────────────────────────

@app.get("/dashboard/datos")
async def dashboard_datos(agente_id: str = "", dias: int = 30) -> dict:
    """Retorna métricas y series para el dashboard de Analytics."""
    return _analytics.dashboard_datos(agente_id=agente_id, dias=dias)


@app.get("/dashboard/briefing")
async def dashboard_briefing(tema: str = "", agente_id: str = "") -> dict:
    """Busca información web sobre el tema usando Tavily y lo retorna como JSON estructurado."""
    return await _insights.briefing(tema=tema, agente_id=agente_id)


@app.get("/dashboard/resumen-ia")
async def dashboard_resumen_ia(dias: int = 30, agente_id: str = "") -> dict:
    """Genera un resumen ejecutivo en español con el LLM usando los datos del dashboard."""
    return await _insights.resumen_ia(dias=dias, agente_id=agente_id)


@app.get("/dashboard/leer-pagina")
async def dashboard_leer_pagina(url: str) -> dict:
    """Extrae el contenido legible de una URL usando Tavily Extract + fallback HTTP."""
    if not url.strip():
        return {"url": url, "contenido": ""}
    from core.tools import _obtener_pagina
    contenido = await _obtener_pagina(url.strip(), max_chars=7000)
    return {"url": url, "contenido": contenido}


# ── Monitor Web + Base de datos ───────────────────────────────────────────────

@app.get("/monitor/fetch")
async def monitor_fetch(categoria: str, params: str = "{}") -> dict:
    """
    Fetch de datos en tiempo real desde una fuente web.
    categoria: futbol_equipo | futbol_multiple | energia_renovable | energia_spot | energia_demanda
    params: JSON string con parámetros adicionales
    """
    from core.web_monitor import fetch_categoria
    from core.database   import guardar_dato_monitor
    import json as _json
    try:
        p      = _json.loads(params)
        result = await fetch_categoria(categoria, p)

        # Persistir en SQLite si hay datos numéricos
        if isinstance(result, dict) and "estadisticas" in result:
            st = result["estadisticas"]
            for k, v in st.items():
                if isinstance(v, (int, float)):
                    guardar_dato_monitor(0, categoria, categoria, f"{result.get('nombre','')}/{k}",
                                        str(v), float(v))
        elif isinstance(result, dict) and "solar" in result:
            for k, v in result.get("solar",{}).items():
                if isinstance(v, (int,float)):
                    guardar_dato_monitor(0, "energia", "energia", f"solar/{k}", str(v), float(v))

        await manager.broadcast({"tipo":"monitor_actualizado","categoria":categoria})
        return {"ok": True, "categoria": categoria, "data": result}
    except Exception as exc:
        logger.error("monitor_fetch: %s", exc)
        return {"ok": False, "error": str(exc)}


@app.get("/scheduler/tareas")
async def scheduler_tareas() -> dict:
    """Estado de todas las tareas del scheduler."""
    from core.scheduler import get_tareas
    return {"tareas": get_tareas()}


class SchedulerUpdateRequest(BaseModel):
    activo:        bool  | None = None
    intervalo_min: int   | None = None


@app.put("/scheduler/tareas/{tarea_id}")
async def scheduler_update(tarea_id: str, payload: SchedulerUpdateRequest) -> dict:
    """Activar/desactivar o cambiar intervalo de una tarea."""
    from core.scheduler import actualizar_tarea
    result = actualizar_tarea(tarea_id, payload.activo, payload.intervalo_min)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Tarea '{tarea_id}' no encontrada.")
    await manager.broadcast({"tipo": "scheduler_actualizado", "tarea_id": tarea_id})
    return {"ok": True, "tareas": result}


@app.post("/scheduler/tareas/{tarea_id}/ejecutar")
async def scheduler_ejecutar_ahora(tarea_id: str) -> dict:
    """Ejecuta una tarea del scheduler inmediatamente."""
    from core.scheduler import ejecutar_ahora
    ok = await ejecutar_ahora(tarea_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Tarea '{tarea_id}' no encontrada.")
    return {"ok": True, "mensaje": f"Tarea '{tarea_id}' iniciada en background"}


@app.get("/monitor/equipos-preset")
async def monitor_equipos_preset() -> dict:
    """Lista de equipos y ligas disponibles."""
    from core.web_monitor import EQUIPOS_PRESET, LIGAS_CATALOGO
    return {"equipos": EQUIPOS_PRESET, "ligas": LIGAS_CATALOGO}


@app.get("/monitor/liga/{liga_id}")
async def monitor_liga(liga_id: str, nombre: str = "") -> dict:
    """Datos completos de una liga: tabla, partidos, estadísticas."""
    from core.web_monitor import fetch_futbol_liga_completo
    try:
        resultado = await fetch_futbol_liga_completo(liga_id, nombre)
        # Persistir tabla en SQLite
        from core.database import guardar_dato_monitor
        for eq in resultado.get("equipos_tabla", []):
            guardar_dato_monitor(
                fuente_id=0, fuente_nombre=f"Liga:{nombre or liga_id}",
                categoria="futbol_liga", clave=f"{nombre}/{eq['equipo']}/puntos",
                valor=str(eq["puntos"]), valor_numerico=float(eq["puntos"]),
            )
        await manager.broadcast({"tipo": "monitor_actualizado", "categoria": "futbol_liga", "liga": nombre})
        return {"ok": True, "data": resultado}
    except Exception as exc:
        logger.error("monitor_liga %s: %s", liga_id, exc)
        return {"ok": False, "error": str(exc)}


@app.get("/monitor/historial")
async def monitor_historial(
    categoria: str | None = None,
    clave: str | None = None,
    limit: int = 100,
) -> dict:
    """Historial de datos monitoreados desde SQLite."""
    from core.database import get_datos_monitor
    return {"datos": get_datos_monitor(categoria=categoria, clave=clave, limit=limit)}


@app.get("/monitor/alertas")
async def monitor_alertas(no_leidas: bool = False) -> dict:
    """Alertas generadas por el monitor."""
    from core.database import get_alertas, marcar_alertas_leidas
    alertas = get_alertas(solo_no_leidas=no_leidas)
    if no_leidas: marcar_alertas_leidas()
    return {"alertas": alertas, "total": len(alertas)}


@app.get("/historial/agente/{agente_id}")
async def historial_agente(agente_id: str, limit: int = 50) -> dict:
    """Historial real de ejecuciones de un agente desde SQLite."""
    from core.database import get_historial, get_stats_agente
    return {
        "historial": get_historial(agente_id=agente_id, limit=limit),
        "stats":     get_stats_agente(agente_id),
    }


@app.get("/historial")
async def historial_global(limit: int = 100) -> dict:
    """Historial global de todas las ejecuciones."""
    from core.database import get_historial
    return {"historial": get_historial(limit=limit)}


@app.get("/tendencias/{agente_id}")
async def tendencias_agente(agente_id: str, dias: int = 30) -> dict:
    """Tendencias de rendimiento del agente (regresion lineal, analytics_service)."""
    return await _analytics.tendencias_agente(agente_id, dias=dias)


@app.get("/agentes-stats")
async def agentes_stats_all() -> dict:
    """Estadisticas historicas de todos los agentes (formato localStorage v2)."""
    return await _analytics.agentes_stats(dias=90)


# ── Auth JWT + RBAC: endpoints /auth/* movidos a core/api_auth.py ─────────────


# ── Analytics: Curva S / Earned Value Management ──────────────────────────────

@app.get("/analytics/curva-s/{proyecto_id}")
async def analytics_curva_s(proyecto_id: str, req: "Request") -> dict:
    """
    Calcula la Curva S (EVM) del proyecto y emite el resultado vía WebSocket.

    Si SPI o CPI < 0.80 (CRITICO) o < 0.90 (ALTO), también emite un evento
    `curva_s_alerta` para que el cliente React dispare una notificación nativa.

    Requiere rol supervisor o superior.
    """
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")

    from core.analytics import motor_analitica
    resultado = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: motor_analitica.calcular_curva_s(proyecto_id),
    )

    # Broadcast solo a supervisor+ (datos financieros sensibles)
    await manager.broadcast(
        {
            "tipo":        "curva_s_actualizada",
            "proyecto_id": proyecto_id,
            "kpis":        resultado.get("kpis", {}),
            "curva":       resultado.get("curva", []),
            "alerta":      resultado.get("alerta"),
        },
        rol_minimo="supervisor",
    )

    # Notificación proactiva adicional si hay desvío crítico
    if resultado.get("alerta"):
        kpis    = resultado.get("kpis", {})
        spi     = kpis.get("spi", 1.0)
        cpi     = kpis.get("cpi", 1.0)
        nivel   = resultado["alerta"]
        await manager.broadcast(
            {
                "tipo":        "curva_s_alerta",
                "proyecto_id": proyecto_id,
                "nivel":       nivel,
                "titulo":      f"Desvío {nivel} en proyecto {proyecto_id}",
                "cuerpo": (
                    f"SPI={spi:.2f} · CPI={cpi:.2f}. "
                    + ("Cronograma y costos fuera de control." if nivel == "CRITICO"
                       else "Revisar avance y presupuesto.")
                ),
            },
            rol_minimo="supervisor",   # alertas financieras solo para supervisor+
        )

    return resultado


# ── Backup / Restore / Versión ────────────────────────────────────────────────

@app.get("/version")
async def get_version() -> dict:
    """Versión actual de AgentDesk."""
    from core.backup import _version
    return {"version": _version(), "app": "AgentDesk"}


@app.get("/update/check")
async def update_check(url: str = "") -> dict:
    """Verifica si hay una nueva versión disponible."""
    from core.updater import verificar_actualizacion
    return verificar_actualizacion(url or None)


class UpdateURLRequest(BaseModel):
    url: str

@app.put("/update/url")
async def update_set_url(payload: UpdateURLRequest) -> dict:
    """Configura la URL del servidor de actualizaciones."""
    from core.updater import guardar_url_update
    ok = guardar_url_update(payload.url)
    return {"ok": ok, "url": payload.url}


@app.get("/backup/descargar")
async def backup_descargar(req: "Request") -> _Response:
    """Genera y descarga un ZIP con toda la base de datos y configuración. Solo admin (JWT)."""
    from core.api_auth import exigir_admin_auditado
    exigir_admin_auditado(req, "descarga de backup", "GET /backup/descargar", logger)
    from core.backup import crear_backup
    from datetime import datetime as _dt2
    try:
        data = await _queue.ejecutar_pesado(crear_backup)
        ts   = utcnow().strftime("%Y%m%d_%H%M")
        return _Response(
            content    = data,
            media_type = "application/zip",
            headers    = {"Content-Disposition": f'attachment; filename="agentdesk_backup_{ts}.zip"'},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al crear backup: {exc}")


@app.post("/backup/restaurar")
async def backup_restaurar(req: "Request", archivo: UploadFile = _File(...)) -> dict:
    """Restaura un backup desde un ZIP previamente generado. Solo admin (JWT)."""
    from core.api_auth import exigir_admin_auditado
    exigir_admin_auditado(req, "restauracion de backup", "POST /backup/restaurar", logger)
    from core.backup import restaurar_backup
    try:
        data = await archivo.read()
        r    = restaurar_backup(data)
        if r["ok"]:
            await manager.broadcast({"tipo": "backup_restaurado", "total": r["total"]})
        return r
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/rate-limiter/stats")
async def rate_limiter_stats() -> dict:
    """Estadísticas de uso del rate limiter por proveedor."""
    try:
        from core.rate_limiter import get_stats_todos
        return {"stats": get_stats_todos()}
    except Exception as exc:
        return {"stats": [], "error": str(exc)}


# ── Diagnóstico y Auditoría IA (ADR-0007) ─────────────────────────────────────

@app.get("/diagnostico/llm")
async def diagnostico_llm() -> dict:
    """Estado OPEN/CLOSED de los Circuit Breakers y latencias por proveedor."""
    from core.services.llm_service import llm_service
    return {"circuitos": llm_service.estado_circuitos(),
            "cadena": [p for p, _ in llm_service._cadena]}


@app.get("/auditoria/interacciones")
async def auditoria_interacciones(req: "Request", agente_id: str = "",
                                  user_id: str = "", limit: int = 50) -> dict:
    """Trazas forenses de interacciones IA. Requiere rol supervisor o admin."""
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")
    from core.services import audit_service
    return {"interacciones": audit_service.consultar(
        agente_id or None, user_id or None, limit)}


@app.get("/auditoria/costos")
async def auditoria_costos(req: "Request", dias: int = 30) -> dict:
    """Tokens estimados por agente (ventana N días). Supervisor o admin."""
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "supervisor"):
        raise HTTPException(403, detail="Se requiere rol supervisor o admin.")
    from core.services import audit_service
    return audit_service.resumen_costos(dias)


@app.get("/health")
async def health() -> dict:
    agentes_info = {}
    if _orquestador:
        for aid, ag in _orquestador.agentes.items():
            agentes_info[aid] = {
                "nombre":  ag.nombre,
                "modelo":  ag.modelo,
                "area":    getattr(ag, "area", "General"),
                "status":  "idle",
            }
    return {
        "status":    "ok",
        "clientes_ws": len(manager.active),
        "agentes":   agentes_info,
    }


# ── Modelo de entrada para ejecutar tarea ──────────────────────────────────────
class EjecutarRequest(BaseModel):
    tarea:       str      = "reporte_ventas"
    datos_extra: str | None = None   # Texto directo para analizar
    archivo_id:  str | None = None   # ID de archivo subido con /upload


@app.get("/uploads")
async def listar_uploads() -> dict:
    """Lista todos los archivos subidos disponibles para analizar."""
    return _uploads.listar_uploads()


@app.get("/uploads/{archivo_id}/texto")
async def get_upload_texto(archivo_id: str) -> dict:
    """Devuelve el contenido de texto de un archivo subido."""
    try:
        return _uploads.texto_upload(archivo_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/agentes/{agente_id}/ejecutar")
async def ejecutar_agente(agente_id: str, payload: EjecutarRequest, req: "Request") -> dict:
    """
    Ejecuta realizar_tarea() en el agente especificado.
    Emite eventos de telemetría en tiempo real via WebSocket /ws/telemetria.
    Retorna el reporte final o un error detallado.
    """
    try:
        return await _orch_service.ejecutar_tarea(
            agente_id, payload.tarea,
            datos_extra=payload.datos_extra, archivo_id=payload.archivo_id,
            user_id=getattr(req.state, "usuario", None) or "anonimo",
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/agentes")
async def listar_agentes() -> dict:
    """Lista agentes aplanando ubicacion.lat/lng al nivel raíz para el mapa React."""
    return _agent_service.listar()


@app.delete("/agentes/{agente_id}")
async def eliminar_agente(agente_id: str) -> dict:
    """Elimina un agente del sistema y de config.json."""
    try:
        return await _agent_service.eliminar(agente_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Modelo de entrada para actualizar agente ───────────────────────────────────
class ActualizarAgenteRequest(BaseModel):
    nombre:      str  | None = None
    tipo_ia:     str  | None = None
    area:        str  | None = None
    modelo:      str  | None = None
    temperatura: float| None = None
    idioma:      str  | None = None
    prompt_base: str  | None = None


@app.put("/agentes/{agente_id}")
async def actualizar_agente(agente_id: str, payload: ActualizarAgenteRequest) -> dict:
    """Actualiza parámetros de un agente existente con validación Pydantic."""
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        return await _agent_service.actualizar(agente_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/proveedores")
async def listar_proveedores() -> dict:
    """Devuelve todos los proveedores de IA disponibles y sus modelos."""
    from core.providers import modelos_disponibles, proveedores_configurados
    return {
        "proveedores":  proveedores_configurados(),
        "modelos":      modelos_disponibles(),
    }


@app.put("/proveedores/apikey")
async def guardar_api_key(payload: dict) -> dict:
    """Guarda una API key de proveedor en .env + vault (lógica en providers)."""
    proveedor = payload.get("proveedor", "").upper()
    api_key   = payload.get("api_key", "").strip()
    if not proveedor or not api_key:
        raise HTTPException(status_code=400, detail="proveedor y api_key son requeridos.")
    from core.providers import guardar_api_key as _guardar
    return _guardar(proveedor, api_key)


@app.get("/modelos")
async def listar_modelos() -> dict:
    """Devuelve todos los modelos de todos los proveedores configurados."""
    from core.providers import modelos_disponibles
    return {"modelos": modelos_disponibles()}


# ── Modelo de entrada para crear agente ────────────────────────────────────────
class NuevoAgenteRequest(BaseModel):
    nombre:      str
    tipo_ia:     str
    area:        str
    modelo:      str      = "models/gemini-2.5-flash"
    temperatura: float    = 0.4
    idioma:      str      = "espanol"
    prompt_base: str      = ""


# ── Chat libre con agentes ─────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    mensaje:    str
    agente_id:  str | None = None
    archivo_id: str | None = None
    sesion_id:  str        = "default"   # ID de sesión para memoria persistente


@app.post("/chat")
async def chat(payload: ChatRequest, req: "Request") -> dict:
    """Envía un mensaje conversacional a un agente. El orquestador elige el agente si no se especifica."""
    return await _orch_service.chat(
        payload.mensaje, agente_id=payload.agente_id,
        archivo_id=payload.archivo_id, sesion_id=payload.sesion_id,
        user_id=getattr(req.state, "usuario", None) or "anonimo",
    )


@app.get("/memoria/{agente_id}/sesiones")
async def memoria_sesiones(agente_id: str) -> dict:
    """Lista las sesiones de conversación de un agente."""
    from core.memory import get_sesiones_agente
    return {"sesiones": get_sesiones_agente(agente_id)}


@app.get("/memoria/{agente_id}/historial/{sesion_id}")
async def memoria_historial(agente_id: str, sesion_id: str) -> dict:
    """Historial completo de una sesión de conversación."""
    from core.memory import get_historial_sesion
    return {"mensajes": get_historial_sesion(agente_id, sesion_id)}


@app.delete("/memoria/{agente_id}/sesion/{sesion_id}")
async def memoria_limpiar(agente_id: str, sesion_id: str) -> dict:
    """Elimina todos los mensajes de una sesión (resetear conversación)."""
    from core.memory import limpiar_sesion
    limpiar_sesion(agente_id, sesion_id)
    return {"ok": True}


from fastapi.responses import StreamingResponse as _StreamingResponse

@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest, req: "Request") -> _StreamingResponse:
    """
    Versión STREAMING del chat — devuelve Server-Sent Events (SSE).
    El motor genera eventos dict (orchestrator_service); aquí solo se
    serializan a SSE — puro adaptador de transporte.
    """
    import json as _json
    _user = getattr(req.state, "usuario", None) or "anonimo"

    async def event_generator():
        async for evento in _orch_service.chat_stream(
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


@app.post("/upload")
async def upload_archivo(archivo: UploadFile = _File(...)) -> dict:
    """Sube un archivo para análisis. Devuelve archivo_id + preview de CSV/Excel."""
    contenido = await archivo.read()
    return _uploads.guardar_upload(archivo.filename or "archivo", contenido)


class GenerarPDFRequest(BaseModel):
    reporte:        dict
    titulo:         str  = "Informe de Análisis"
    subtitulo:      str  = ""
    nombre_agente:  str  = "AgentDesk"
    archivo_nombre: str  = ""
    empresa:        str  = "AgentDesk"


@app.post("/generar-pdf")
async def generar_pdf(payload: GenerarPDFRequest) -> dict:
    """Genera un informe PDF, lo guarda en reportes/ y devuelve la URL de descarga."""
    try:
        from core.report_generator import generar_pdf as _gen_pdf
        from core.path_manager import data_path
        from datetime import datetime as _dt
        pdf_bytes = await _queue.ejecutar_pesado(
            _gen_pdf,
            reporte        = payload.reporte,
            titulo         = payload.titulo,
            subtitulo      = payload.subtitulo,
            nombre_agente  = payload.nombre_agente,
            archivo_nombre = payload.archivo_nombre,
            empresa        = payload.empresa,
        )
        reportes_dir = data_path("reportes")
        reportes_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        nombre_archivo = payload.titulo.replace(" ", "_")[:30] + f"_{ts}.pdf"
        (reportes_dir / nombre_archivo).write_bytes(pdf_bytes)
        return {"ok": True, "filename": nombre_archivo, "url": f"/reportes/{nombre_archivo}"}
    except Exception as exc:
        logger.error("generar_pdf error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Error al generar PDF: {exc}")


@app.get("/alertas/config")
async def get_alertas_config() -> dict:
    """Lee la configuración de umbrales para alertas económicas."""
    return _pipeline_service.get_alertas_config()


class AlertasConfigRequest(BaseModel):
    dolar_max: float | None = None
    dolar_min: float | None = None
    uf_max:    float | None = None
    ipc_max:   float | None = None


@app.put("/alertas/config")
async def set_alertas_config(payload: AlertasConfigRequest) -> dict:
    """Actualiza umbrales de alertas económicas."""
    return _pipeline_service.set_alertas_config(payload.model_dump())


@app.get("/indicadores/live")
async def indicadores_live() -> dict:
    """Retorna UF, dólar, euro, IPC actuales del Banco Central en tiempo real."""
    try:
        from core.web_monitor import fetch_indicadores_economia
        data = await fetch_indicadores_economia()
        if "error" in data:
            raise HTTPException(status_code=502, detail=data["error"])
        return {"indicadores": data, "fuente": "mindicador.cl"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/pipeline/config")
async def get_pipeline_config() -> dict:
    """Lee la configuración de umbrales de los guardrails."""
    return _pipeline_service.get_config()


class PipelineConfigRequest(BaseModel):
    recursion_umbral: int   | None = None
    grounding_min:    int   | None = None
    logic_factor:     int   | None = None
    timeout_s:        float | None = None


@app.put("/pipeline/config")
async def set_pipeline_config(payload: PipelineConfigRequest) -> dict:
    """
    Actualiza los umbrales de los guardrails.
    Los cambios se aplican en la próxima ejecución de agentes.
    """
    return _pipeline_service.set_config(payload.model_dump())


@app.get("/embeddings")
async def get_embeddings() -> dict:
    """
    Embeddings semánticos reales usando TF-IDF + PCA.
    Los agentes similares (mismo dominio, mismos temas) quedan CERCANOS en 3D.
    """
    return await _queue.ejecutar_pesado(_analytics.embeddings_3d, _orquestador)


@app.get("/kill-switch")
async def estado_kill_switch() -> dict:
    """
    Retorna el estado actual del kill switch (incluye gist_url para la UI).
    El monitor de background actualiza el estado cada 5 minutos.
    """
    return kill_switch.estado_dict()


class KillSwitchURLRequest(BaseModel):
    url: str = ""


class KillSwitchToggleRequest(BaseModel):
    activo: bool


@app.post("/kill-switch/toggle")
async def toggle_kill_switch(payload: KillSwitchToggleRequest) -> dict:
    """
    Activa o bloquea el Kill Switch manualmente desde el SecurityPanel.
    Requiere rol admin (verificado por JWTMiddleware).
    El monitor del Gist puede sobreescribir este estado en la siguiente verificación.
    """
    kill_switch.forzar_estado(payload.activo)
    logger.info("Kill switch toggled a %s via API.", payload.activo)
    return kill_switch.estado_dict()


@app.post("/kill-switch/url")
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


# ── Modelo de entrada para RELOAD_CONFIG ──────────────────────────────────────
class ReloadRequest(BaseModel):
    agente_id: str | None = None   # None → recargar todos los agentes


@app.post("/reload")
async def recargar_config(payload: ReloadRequest) -> dict:
    """
    Envía RELOAD_CONFIG al CommandBridge.

    El Orquestador re-lee config.json, valida cada agente con Pydantic
    y aplica los cambios en caliente.  Si la validación falla, el agente
    mantiene su configuración anterior (rollback implícito).

    payload.agente_id: ID del agente a recargar, o null para todos.
    """
    return await _agent_service.recargar(payload.agente_id)


@app.post("/agentes", status_code=201)
async def crear_agente(payload: NuevoAgenteRequest) -> dict:
    """
    Valida con AgentConfig (Pydantic) y encola CREAR_AGENTE en el CommandBridge.
    El Orquestador consume el comando y persiste en config.json.
    """
    return await _agent_service.crear(payload.model_dump())


# ── Endpoints de reportes PDF (lógica en report_service) ──────────────────────

@app.get("/agentes/{agente_id}/reporte")
async def descargar_reporte(agente_id: str) -> FileResponse:
    """
    Devuelve el PDF de éxito más reciente del agente como descarga directa.

    Busca en %APPDATA%\\AgentDesk\\reportes\\ archivos de la forma:
      reporte_{slug}_{YYYYMMDD}_{HHMMSS}.pdf

    Responde 404 si el agente aún no tiene reportes (no ha ejecutado el pipeline).
    """
    pdf = _reports.buscar_pdf("reporte", agente_id)
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


@app.get("/agentes/{agente_id}/correccion")
async def descargar_correccion(agente_id: str) -> FileResponse:
    """Devuelve el PDF de corrección más reciente del agente."""
    pdf = _reports.buscar_pdf("correccion", agente_id)
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


@app.get("/agentes/{agente_id}/reportes")
async def listar_reportes(agente_id: str) -> dict:
    """
    Lista todos los PDFs disponibles para el agente (éxito + correcciones).
    Ordenados por fecha descendente.
    """
    return _reports.listar_por_agente(agente_id)


# ── Motor Financiero ───────────────────────────────────────────────────────────

class PresupuestoPayload(BaseModel):
    """Payload para POST /finanzas/analizar."""
    agente_id:   str
    presupuesto: dict
    periodos:    int = 6


@app.get("/finanzas/indicadores")
async def finanzas_indicadores() -> dict:
    """Indicadores macro Chile en tiempo real (UF, Dólar, IPC, Euro)."""
    from core.finance import motor_financiero
    try:
        ind = await motor_financiero.obtener_indicadores()
        return {"ok": True, "indicadores": ind.model_dump(mode="json")}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}


@app.post("/finanzas/analizar")
async def finanzas_analizar(payload: PresupuestoPayload) -> dict:
    """
    Análisis financiero completo: valida con Pydantic v2, obtiene indicadores
    reales del Banco Central y persiste en agentdesk.db (rollback si falla).
    """
    from pydantic import ValidationError
    from core.schemas import PresupuestoConfig
    from core.finance import motor_financiero

    try:
        presupuesto = PresupuestoConfig.model_validate(payload.presupuesto)
    except ValidationError as e:
        raise HTTPException(422, detail={"error": "Presupuesto inválido", "detalle": e.errors()})

    try:
        resultado = await motor_financiero.analizar_y_persistir(
            payload.agente_id, presupuesto, periodos=payload.periodos,
        )
        return {"ok": True, "analisis": resultado}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/finanzas/historico/{agente_id}")
async def finanzas_historico(agente_id: str, n: int = 10) -> dict:
    """Historial de análisis financieros del agente (últimos N registros)."""
    from core.finance import motor_financiero
    registros = motor_financiero.historico(agente_id, n=min(n, 50))
    return {"agente_id": agente_id, "registros": registros}


@app.get("/finanzas/tendencia/{agente_id}")
async def finanzas_tendencia(agente_id: str, n: int = 10) -> dict:
    """Estadísticas de tendencia del flujo neto histórico del agente."""
    from core.finance import motor_financiero
    return motor_financiero.tendencia_flujo(agente_id, n=n)


@app.post("/finanzas/reload/{agente_id}")
async def finanzas_reload_presupuesto(agente_id: str, presupuesto: dict) -> dict:
    """Recarga el presupuesto de un agente en caliente (RELOAD_FINANZAS via CommandBridge)."""
    if not _bridge:
        raise HTTPException(503, detail="Bridge no disponible — orquestador no en línea")
    await _bridge.send(Command(
        tipo=RELOAD_FINANZAS,
        payload={"agente_id": agente_id, "presupuesto": presupuesto},
    ))
    return {"ok": True, "mensaje": f"RELOAD_FINANZAS encolado para '{agente_id}'"}


# ── Motor Gantt ────────────────────────────────────────────────────────────────

@app.get("/gantt/proyectos")
async def gantt_listar_proyectos() -> dict:
    """Lista todos los proyectos Gantt con su resumen de avance."""
    from core.gantt import motor_gantt
    return {"proyectos": motor_gantt.listar_proyectos()}


@app.get("/gantt/{proyecto_id}")
async def gantt_obtener_proyecto(proyecto_id: str) -> dict:
    """Retorna todas las tareas y el resumen CPM de un proyecto."""
    from core.gantt import motor_gantt
    return motor_gantt.obtener_proyecto(proyecto_id)


@app.post("/gantt/{proyecto_id}/tareas")
async def gantt_crear_tarea(proyecto_id: str, datos: dict) -> dict:
    """Crea una tarea en el proyecto y recalcula la Ruta Crítica (CPM)."""
    from core.gantt import motor_gantt
    datos["proyecto_id"] = proyecto_id
    try:
        return motor_gantt.crear_tarea(datos)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@app.put("/gantt/tareas/{tarea_id}")
async def gantt_actualizar_tarea(tarea_id: int, datos: dict) -> dict:
    """Actualiza parámetros de una tarea y recalcula Forward/Backward pass."""
    from core.gantt import motor_gantt
    try:
        return motor_gantt.actualizar_tarea(tarea_id, datos)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@app.patch("/gantt/tareas/{tarea_id}/progreso")
async def gantt_actualizar_progreso(tarea_id: int, datos: dict) -> dict:
    """Actualiza el % de avance de una tarea con validación Pydantic (rollback si falla)."""
    from core.gantt import motor_gantt
    try:
        resultado = motor_gantt.actualizar_progreso(tarea_id, datos)
        # Broadcast del nuevo estado a todos los clientes WS
        await manager.broadcast({
            "tipo":      "gantt_progreso",
            "tarea_id":  tarea_id,
            "pct":       resultado["pct_completado"],
            "proyecto":  resultado["proyecto_id"],
        })
        return resultado
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@app.delete("/gantt/tareas/{tarea_id}")
async def gantt_eliminar_tarea(tarea_id: int) -> dict:
    """Elimina una tarea y recalcula el CPM del proyecto."""
    from core.gantt import motor_gantt
    ok = motor_gantt.eliminar_tarea(tarea_id)
    if not ok:
        raise HTTPException(404, detail=f"Tarea {tarea_id} no encontrada")
    return {"ok": True, "eliminada": tarea_id}


@app.get("/gantt/{proyecto_id}/pdf")
async def gantt_exportar_pdf(
    proyecto_id: str,
    agente_id: str | None = None,
) -> _Response:
    """
    Genera un Reporte de Avance de Obra en PDF con:
      - Cronograma Gantt (barras horizontales con progreso)
      - Indicadores financieros en tiempo real (UF, Dólar, IPC)
      - Resumen de tareas críticas y avance global
    """
    from core.gantt import motor_gantt
    from core.finance import motor_financiero

    proyecto = motor_gantt.obtener_proyecto(proyecto_id)
    if not proyecto["tareas"]:
        raise HTTPException(404, detail=f"Proyecto '{proyecto_id}' sin tareas")

    # Intentar obtener indicadores financieros (sin bloquear si falla)
    indicadores = None
    try:
        indicadores = await motor_financiero.obtener_indicadores()
    except RuntimeError:
        pass

    from core.services.gantt_report_service import generar_pdf_gantt
    # Trabajo pesado fuera del event loop (QueuePort) — el Dashboard no se cuelga
    pdf_bytes = await _queue.ejecutar_pesado(generar_pdf_gantt, proyecto, indicadores, agente_id)

    nombre = f"avance_{proyecto_id}_{utcnow().strftime('%Y%m%d_%H%M')}.pdf"
    return _Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# ── Webhook WhatsApp / Control Remoto ─────────────────────────────────────────

class WhatsAppWebhookPayload(BaseModel):
    """Payload del webhook remoto (WhatsApp, curl, cron, etc.)."""
    mensaje:     str
    clave:       str            # contraseña en texto plano — validada contra MASTER_PASSWORD_HASH
    from_number: str = ""       # opcional: número origen para auditoría


@app.post("/webhook/whatsapp")
async def webhook_whatsapp(payload: WhatsAppWebhookPayload) -> dict:
    """
    Control remoto por webhook.  Auth: MASTER_PASSWORD_HASH (bcrypt).

    Diseñado para integraciones WhatsApp Business API, cron jobs o clientes HTTP.
    No expone token JWT: cada request lleva la clave y se valida en tiempo real.
    Timeout interno de 4s para no bloquear el event loop en servidores lentos.
    """
    import bcrypt as _bcrypt

    hash_env = os.environ.get("MASTER_PASSWORD_HASH", "").strip()
    if not hash_env:
        raise HTTPException(503, detail="Sistema no configurado: MASTER_PASSWORD_HASH ausente en .env")

    # Validar con timeout para evitar timing attacks sin bloquear el loop
    try:
        autorizado = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _bcrypt.checkpw(
                    payload.clave.encode("utf-8"),
                    hash_env.encode("utf-8"),
                ),
            ),
            timeout=4.0,
        )
    except (asyncio.TimeoutError, Exception):
        autorizado = False

    if not autorizado:
        raise HTTPException(401, detail="Clave inválida.")

    logger.info(
        "Webhook WhatsApp recibido de %s: %s",
        payload.from_number or "desconocido",
        payload.mensaje.strip(),
    )
    return {"respuesta": await _orch_service.comando_remoto(payload.mensaje)}


# ── Compliance ────────────────────────────────────────────────────────────────

@app.get("/compliance/reporte")
async def compliance_reporte(
    agente_id: str | None = None,
    dias: int = 30,
) -> dict:
    """
    Reporte de cumplimiento de guardrails.
    Agrupa abortos por guardrail y agente, emite alertas y sugerencias de temperatura.
    """
    from core.compliance import motor_compliance
    return motor_compliance.reporte_cumplimiento(agente_id=agente_id, dias=dias)


# ── Riesgo ────────────────────────────────────────────────────────────────────

@app.get("/riesgo/analisis/{proyecto_id}")
async def riesgo_analisis(proyecto_id: str) -> dict:
    """
    Correlaciona desviaciones del Gantt con impacto financiero proyectado.
    Retorna alertas ordenadas por nivel (CRITICO → ALTO → MEDIO).
    """
    from core.risk_engine import motor_riesgo
    return motor_riesgo.analizar_proyecto(proyecto_id)


# ── Salud del sistema (BI Dashboard) ─────────────────────────────────────────

@app.get("/sistema/salud")
async def sistema_salud() -> dict:
    """
    KPIs maestros consolidados: Gantt + Finanzas + Compliance + Riesgo.
    Score 0-100 ponderado para el Central Control Panel (BIDashboard ID 9).
    """
    from core.risk_engine import motor_riesgo
    return motor_riesgo.salud_sistema()


@app.get("/docs/manual")
async def descargar_manual(empresa: str = "AgentDesk") -> _Response:
    """
    Genera y descarga el Manual de Usuario en PDF personalizado con el nombre de la empresa.
    Ejemplo: GET /docs/manual?empresa=ACME+S.A.
    """
    from core.docs_gen import generar_manual
    loop      = asyncio.get_running_loop()
    pdf_bytes = await loop.run_in_executor(None, lambda: generar_manual(empresa))
    nombre    = f"Manual_AgentDesk_{empresa.replace(' ', '_')}.pdf"
    return _Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


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
