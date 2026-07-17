"""
core/api/monitor_router.py — Monitoreo web/planta, scheduler automático,
dashboard de analytics, alertas, configuración del pipeline (guardrails),
Curva S / EVM, compliance y análisis de riesgo.

Extraído de core/api.py (Fase 17, ADR-0015).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

import core.api._state as _state
from core.api.schemas import (
    AlertasConfigRequest,
    PipelineConfigRequest,
    SchedulerUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Dashboard Analytics ───────────────────────────────────────────────────────

@router.get("/dashboard/datos")
async def dashboard_datos(agente_id: str = "", dias: int = 30) -> dict:
    """Retorna métricas y series para el dashboard de Analytics."""
    return _state._analytics.dashboard_datos(agente_id=agente_id, dias=dias)


@router.get("/dashboard/briefing")
async def dashboard_briefing(tema: str = "", agente_id: str = "") -> dict:
    """Busca información web sobre el tema usando Tavily y lo retorna como JSON estructurado."""
    return await _state._insights.briefing(tema=tema, agente_id=agente_id)


@router.get("/dashboard/resumen-ia")
async def dashboard_resumen_ia(dias: int = 30, agente_id: str = "") -> dict:
    """Genera un resumen ejecutivo en español con el LLM usando los datos del dashboard."""
    return await _state._insights.resumen_ia(dias=dias, agente_id=agente_id)


@router.get("/dashboard/leer-pagina")
async def dashboard_leer_pagina(url: str) -> dict:
    """Extrae el contenido legible de una URL usando Tavily Extract + fallback HTTP."""
    if not url.strip():
        return {"url": url, "contenido": ""}
    from core.tools import _obtener_pagina
    contenido = await _obtener_pagina(url.strip(), max_chars=7000)
    return {"url": url, "contenido": contenido}


# ── Monitor Web + Base de datos ───────────────────────────────────────────────

@router.get("/monitor/fetch")
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

        await _state.manager.broadcast({"tipo":"monitor_actualizado","categoria":categoria})
        return {"ok": True, "categoria": categoria, "data": result}
    except Exception as exc:
        logger.error("monitor_fetch: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.get("/scheduler/tareas")
async def scheduler_tareas() -> dict:
    """Estado de todas las tareas del scheduler."""
    from core.scheduler import get_tareas
    return {"tareas": get_tareas()}


@router.put("/scheduler/tareas/{tarea_id}")
async def scheduler_update(tarea_id: str, payload: SchedulerUpdateRequest) -> dict:
    """Activar/desactivar o cambiar intervalo de una tarea."""
    from core.scheduler import actualizar_tarea
    result = actualizar_tarea(tarea_id, payload.activo, payload.intervalo_min)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Tarea '{tarea_id}' no encontrada.")
    await _state.manager.broadcast({"tipo": "scheduler_actualizado", "tarea_id": tarea_id})
    return {"ok": True, "tareas": result}


@router.post("/scheduler/tareas/{tarea_id}/ejecutar")
async def scheduler_ejecutar_ahora(tarea_id: str) -> dict:
    """Ejecuta una tarea del scheduler inmediatamente."""
    from core.scheduler import ejecutar_ahora
    ok = await ejecutar_ahora(tarea_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Tarea '{tarea_id}' no encontrada.")
    return {"ok": True, "mensaje": f"Tarea '{tarea_id}' iniciada en background"}


@router.get("/monitor/equipos-preset")
async def monitor_equipos_preset() -> dict:
    """Lista de equipos y ligas disponibles."""
    from core.web_monitor import EQUIPOS_PRESET, LIGAS_CATALOGO
    return {"equipos": EQUIPOS_PRESET, "ligas": LIGAS_CATALOGO}


@router.get("/monitor/liga/{liga_id}")
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
        await _state.manager.broadcast({"tipo": "monitor_actualizado", "categoria": "futbol_liga", "liga": nombre})
        return {"ok": True, "data": resultado}
    except Exception as exc:
        logger.error("monitor_liga %s: %s", liga_id, exc)
        return {"ok": False, "error": str(exc)}


@router.get("/monitor/historial")
async def monitor_historial(
    categoria: str | None = None,
    clave: str | None = None,
    limit: int = 100,
) -> dict:
    """Historial de datos monitoreados desde SQLite."""
    from core.database import get_datos_monitor
    return {"datos": get_datos_monitor(categoria=categoria, clave=clave, limit=limit)}


@router.get("/monitor/alertas")
async def monitor_alertas(no_leidas: bool = False) -> dict:
    """Alertas generadas por el monitor."""
    from core.database import get_alertas, marcar_alertas_leidas
    alertas = get_alertas(solo_no_leidas=no_leidas)
    if no_leidas: marcar_alertas_leidas()
    return {"alertas": alertas, "total": len(alertas)}


# ── Analytics: Curva S / Earned Value Management ──────────────────────────────

@router.get("/analytics/curva-s/{proyecto_id}")
async def analytics_curva_s(proyecto_id: str, req: Request) -> dict:
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
    await _state.manager.broadcast(
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
        await _state.manager.broadcast(
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
        await _state.manager.broadcast(
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


@router.get("/alertas/config")
async def get_alertas_config() -> dict:
    """Lee la configuración de umbrales para alertas económicas."""
    return _state._pipeline_service.get_alertas_config()


@router.put("/alertas/config")
async def set_alertas_config(payload: AlertasConfigRequest) -> dict:
    """Actualiza umbrales de alertas económicas."""
    return _state._pipeline_service.set_alertas_config(payload.model_dump())


@router.get("/indicadores/live")
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


@router.get("/pipeline/config")
async def get_pipeline_config() -> dict:
    """Lee la configuración de umbrales de los guardrails."""
    return _state._pipeline_service.get_config()


@router.put("/pipeline/config")
async def set_pipeline_config(payload: PipelineConfigRequest) -> dict:
    """
    Actualiza los umbrales de los guardrails.
    Los cambios se aplican en la próxima ejecución de agentes.
    """
    return _state._pipeline_service.set_config(payload.model_dump())


# ── Compliance / Riesgo ────────────────────────────────────────────────────────

@router.get("/compliance/reporte")
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


@router.get("/riesgo/analisis/{proyecto_id}")
async def riesgo_analisis(proyecto_id: str) -> dict:
    """
    Correlaciona desviaciones del Gantt con impacto financiero proyectado.
    Retorna alertas ordenadas por nivel (CRITICO → ALTO → MEDIO).
    """
    from core.risk_engine import motor_riesgo
    return motor_riesgo.analizar_proyecto(proyecto_id)
