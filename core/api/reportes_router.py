"""
core/api/reportes_router.py — Reportes PDF genéricos, generación de PDF a
demanda, motor Gantt (CRUD + exportación), motor Financiero y webhook de
control remoto (WhatsApp / curl / cron).

Extraído de core/api.py (Fase 17, ADR-0015).
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse as _FileResponse, Response as _Response

from core.timeutil import utcnow
from core.command_bridge import Command, RELOAD_FINANZAS
import core.api._state as _state
from core.api.schemas import GenerarPDFRequest, PresupuestoPayload, WhatsAppWebhookPayload

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Reportes genéricos ─────────────────────────────────────────────────────────

@router.get("/reportes")
async def listar_todos_reportes() -> dict:
    """Lista todos los reportes PDF de todos los agentes."""
    return _state._reports.listar_todos()


@router.get("/reportes/{nombre}")
async def descargar_reporte_directo(nombre: str) -> _FileResponse:
    """Descarga un archivo de reportes por nombre."""
    try:
        archivo = _state._reports.ruta_reporte(nombre)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    media = "application/pdf" if archivo.suffix == ".pdf" else "text/plain"
    return _FileResponse(str(archivo), filename=nombre, media_type=media,
                         headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/reportes/{nombre}/abrir")
async def abrir_reporte_os(nombre: str) -> dict:
    """Abre el archivo con la aplicación predeterminada del sistema operativo."""
    try:
        os.startfile(str(_state._reports.ruta_reporte(nombre)))
        return {"ok": True, "nombre": nombre}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al abrir archivo: {exc}")


@router.post("/generar-pdf")
async def generar_pdf(payload: GenerarPDFRequest) -> dict:
    """Genera un informe PDF, lo guarda en reportes/ y devuelve la URL de descarga."""
    try:
        from core.report_generator import generar_pdf as _gen_pdf
        from core.path_manager import data_path
        from datetime import datetime as _dt
        pdf_bytes = await _state._queue.ejecutar_pesado(
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


# ── Motor Financiero ───────────────────────────────────────────────────────────

@router.get("/finanzas/indicadores")
async def finanzas_indicadores() -> dict:
    """Indicadores macro Chile en tiempo real (UF, Dólar, IPC, Euro)."""
    from core.finance import motor_financiero
    try:
        ind = await motor_financiero.obtener_indicadores()
        return {"ok": True, "indicadores": ind.model_dump(mode="json")}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}


@router.post("/finanzas/analizar")
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


@router.get("/finanzas/historico/{agente_id}")
async def finanzas_historico(agente_id: str, n: int = 10) -> dict:
    """Historial de análisis financieros del agente (últimos N registros)."""
    from core.finance import motor_financiero
    registros = motor_financiero.historico(agente_id, n=min(n, 50))
    return {"agente_id": agente_id, "registros": registros}


@router.get("/finanzas/tendencia/{agente_id}")
async def finanzas_tendencia(agente_id: str, n: int = 10) -> dict:
    """Estadísticas de tendencia del flujo neto histórico del agente."""
    from core.finance import motor_financiero
    return motor_financiero.tendencia_flujo(agente_id, n=n)


@router.post("/finanzas/reload/{agente_id}")
async def finanzas_reload_presupuesto(agente_id: str, presupuesto: dict) -> dict:
    """Recarga el presupuesto de un agente en caliente (RELOAD_FINANZAS via CommandBridge)."""
    if not _state._bridge:
        raise HTTPException(503, detail="Bridge no disponible — orquestador no en línea")
    await _state._bridge.send(Command(
        tipo=RELOAD_FINANZAS,
        payload={"agente_id": agente_id, "presupuesto": presupuesto},
    ))
    return {"ok": True, "mensaje": f"RELOAD_FINANZAS encolado para '{agente_id}'"}


# ── Motor Gantt ────────────────────────────────────────────────────────────────

@router.get("/gantt/proyectos")
async def gantt_listar_proyectos() -> dict:
    """Lista todos los proyectos Gantt con su resumen de avance."""
    from core.gantt import motor_gantt
    return {"proyectos": motor_gantt.listar_proyectos()}


@router.get("/gantt/{proyecto_id}")
async def gantt_obtener_proyecto(proyecto_id: str) -> dict:
    """Retorna todas las tareas y el resumen CPM de un proyecto."""
    from core.gantt import motor_gantt
    return motor_gantt.obtener_proyecto(proyecto_id)


@router.post("/gantt/{proyecto_id}/tareas")
async def gantt_crear_tarea(proyecto_id: str, datos: dict) -> dict:
    """Crea una tarea en el proyecto y recalcula la Ruta Crítica (CPM)."""
    from core.gantt import motor_gantt
    datos["proyecto_id"] = proyecto_id
    try:
        return motor_gantt.crear_tarea(datos)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@router.put("/gantt/tareas/{tarea_id}")
async def gantt_actualizar_tarea(tarea_id: int, datos: dict) -> dict:
    """Actualiza parámetros de una tarea y recalcula Forward/Backward pass."""
    from core.gantt import motor_gantt
    try:
        return motor_gantt.actualizar_tarea(tarea_id, datos)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@router.patch("/gantt/tareas/{tarea_id}/progreso")
async def gantt_actualizar_progreso(tarea_id: int, datos: dict) -> dict:
    """Actualiza el % de avance de una tarea con validación Pydantic (rollback si falla)."""
    from core.gantt import motor_gantt
    try:
        resultado = motor_gantt.actualizar_progreso(tarea_id, datos)
        # Broadcast del nuevo estado a todos los clientes WS
        await _state.manager.broadcast({
            "tipo":      "gantt_progreso",
            "tarea_id":  tarea_id,
            "pct":       resultado["pct_completado"],
            "proyecto":  resultado["proyecto_id"],
        })
        return resultado
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@router.delete("/gantt/tareas/{tarea_id}")
async def gantt_eliminar_tarea(tarea_id: int) -> dict:
    """Elimina una tarea y recalcula el CPM del proyecto."""
    from core.gantt import motor_gantt
    ok = motor_gantt.eliminar_tarea(tarea_id)
    if not ok:
        raise HTTPException(404, detail=f"Tarea {tarea_id} no encontrada")
    return {"ok": True, "eliminada": tarea_id}


@router.get("/gantt/{proyecto_id}/pdf")
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
    pdf_bytes = await _state._queue.ejecutar_pesado(generar_pdf_gantt, proyecto, indicadores, agente_id)

    nombre = f"avance_{proyecto_id}_{utcnow().strftime('%Y%m%d_%H%M')}.pdf"
    return _Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# ── Webhook WhatsApp / Control Remoto ─────────────────────────────────────────

@router.post("/webhook/whatsapp")
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
    return {"respuesta": await _state._orch_service.comando_remoto(payload.mensaje)}
