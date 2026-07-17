"""
Kill Switch — activacion por licencia RSA LOCAL (Fase 24, ADR-0022).

Historia: hasta la Fase 23 este modulo consultaba una URL remota de
GitHub — un punto unico de falla y una URL de control externa
incompatible con el modo offline total. Desde ADR-0022 la fuente
de verdad es license.key (firma RSA + machine_id), validada por
core.services.license_service sin tocar la red jamas.

Politica (Zero-Default, coherente con ADR-0016):
  - SIN license.key           → sistema ACTIVO (modo desktop libre; la
                                ausencia es un estado valido zero-config).
  - licencia valida           → sistema ACTIVO  (fuente "licencia").
  - licencia presente INVALIDA→ sistema BLOQUEADO (firma rota, otra
                                maquina o expirada = manipulacion).
  - forzar_estado() manual    → override del admin via UI; el monitor lo
                                re-evalua contra la licencia cada 5 min.

La API publica conserva los nombres que consumen agent_service,
orchestrator_service, sistema_router y main.py: is_active(),
estado_dict(), forzar_estado(), iniciar_monitor().
"""

from __future__ import annotations

import asyncio
import logging
import time

from core.services import license_service

logger = logging.getLogger(__name__)

_INTERVALO_S: float = 300.0   # 5 minutos entre re-validaciones


class _Estado:
    """
    Contenedor del estado mutable del kill switch.
    Las asignaciones bool son atomicas en CPython (GIL) — seguro sin Lock
    para el caso de un unico escritor (la tarea monitor).
    """
    activo:          bool         = True
    fuente:          str          = "default"
    motivo:          str          = "sin_licencia"
    licencia:        dict | None  = None
    ts_verificacion: float | None = None


_estado = _Estado()


# ── API publica ────────────────────────────────────────────────────────────────

def is_active() -> bool:
    """True si los agentes estan autorizados a ejecutarse."""
    return _estado.activo


def estado_dict() -> dict:
    """Estado completo serializable para el endpoint GET /kill-switch."""
    lic = _estado.licencia or {}
    payload = lic.get("payload") or {}
    return {
        "active":                 _estado.activo,
        "fuente":                 _estado.fuente,
        "motivo":                 _estado.motivo,
        "ts_ultima_verificacion": _estado.ts_verificacion,
        "licencia_presente":      bool(lic.get("presente")),
        "licencia_valida":        bool(lic.get("valida")),
        "edicion":                payload.get("edicion"),
        "expira":                 payload.get("expira"),
        "machine_id":             license_service.machine_id(),
    }


def validar_ahora() -> bool:
    """
    Re-evalua license.key de forma sincrona y actualiza el estado.
    Es el chequeo pre-arranque de main.py (--api) y el cuerpo del monitor.
    Cero red: solo disco + criptografia local.
    """
    veredicto = license_service.validar_licencia()
    _estado.licencia        = veredicto
    _estado.motivo          = veredicto["motivo"]
    _estado.ts_verificacion = time.time()

    if not veredicto["presente"]:
        # Sin licencia no hay fuente autoritativa: un override manual del
        # admin (toggle) persiste — mismo comportamiento que el gist ausente.
        if _estado.fuente != "manual":
            _estado.activo = True
            _estado.fuente = "default"
    elif veredicto["valida"]:
        _estado.activo = True
        _estado.fuente = "licencia"
    else:
        _estado.activo = False
        _estado.fuente = "licencia_invalida"
        logger.warning(
            "AUDITORIA_SEGURIDAD: KILL SWITCH ACTIVADO — licencia presente "
            "pero invalida (motivo=%s); ejecucion de agentes bloqueada.",
            veredicto["motivo"],
        )
    return _estado.activo


async def verificar_licencia() -> bool:
    """Version async de validar_ahora() (RSA + disco via to_thread)."""
    return await asyncio.to_thread(validar_ahora)


def instalar_licencia(contenido: str) -> dict:
    """
    Valida y persiste una licencia nueva (endpoint POST /kill-switch/licencia),
    y re-evalua el estado de inmediato — activar una licencia no requiere
    reiniciar. Una licencia invalida se rechaza SIN escribir ni cambiar estado.
    """
    veredicto = license_service.guardar_licencia(contenido)
    if veredicto["valida"]:
        validar_ahora()
    return veredicto


def forzar_estado(activo: bool) -> None:
    """
    Fuerza el estado del kill switch manualmente (POST /kill-switch/toggle).
    El monitor lo re-evaluara contra la licencia en la proxima verificacion.
    """
    _estado.activo          = activo
    _estado.fuente          = "manual"
    _estado.ts_verificacion = time.time()
    nivel = logging.INFO if activo else logging.WARNING
    logger.log(nivel, "Kill switch forzado a %s (manual).", "activo" if activo else "bloqueado")


async def iniciar_monitor(intervalo_s: float = _INTERVALO_S) -> None:
    """
    Tarea background: re-valida license.key periodicamente (detecta
    licencias instaladas/borradas/expiradas en caliente sin reiniciar).
    Lanzar con asyncio.create_task(); se cancela limpiamente al salir.
    """
    logger.info("Kill switch monitor iniciado (licencia local, intervalo=%ds).",
                int(intervalo_s))
    try:
        while True:
            await verificar_licencia()
            await asyncio.sleep(intervalo_s)
    except asyncio.CancelledError:
        logger.info("Kill switch monitor: tarea cancelada limpiamente.")
        raise
