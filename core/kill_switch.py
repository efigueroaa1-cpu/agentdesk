"""
Kill Switch — control de activacion remoto via Gist de GitHub.

El Gist debe exponer un JSON con al menos: { "active": true }
Si "active" es false el sistema bloquea la ejecucion de todos los agentes.

Env var:
    KILL_SWITCH_GIST_URL  — URL raw del Gist (omitir para desactivar el control)

La URL tambien puede actualizarse en tiempo de ejecucion via set_gist_url().

Politica ante fallos de red: fail-open.
  El estado inicial es "activo" para no bloquear el arranque sin conectividad.
  Si la ultima verificacion exitosa fue "active": false y la red cae,
  el estado bloqueado se mantiene hasta que el Gist vuelva a responder.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.request
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# URL mutable en tiempo de ejecucion
_gist_url: str = os.environ.get("KILL_SWITCH_GIST_URL", "")
_TIMEOUT_S:   float = 5.0
_INTERVALO_S: float = 300.0   # 5 minutos entre verificaciones


class _Estado:
    """
    Contenedor del estado mutable del kill switch.
    Las asignaciones bool son atomicas en CPython (GIL) — seguro sin Lock
    para el caso de un unico escritor (la tarea monitor).
    """
    activo:          bool         = True
    fuente:          str          = "default"
    ts_verificacion: float | None = None


_estado = _Estado()


# ── API publica ────────────────────────────────────────────────────────────────

def is_active() -> bool:
    """True si los agentes estan autorizados a ejecutarse."""
    return _estado.activo


def get_gist_url() -> str:
    """Devuelve la URL del Gist actualmente configurada."""
    return _gist_url


def set_gist_url(url: str) -> None:
    """
    Actualiza la URL del Gist en tiempo de ejecucion.
    Si la URL esta vacia, desactiva el control remoto (sistema siempre activo).
    """
    global _gist_url
    _gist_url = url.strip()
    if _gist_url:
        logger.info("Kill switch URL actualizada: %s", _gist_url)
    else:
        _estado.activo = True
        _estado.fuente = "default"
        logger.info("Kill switch URL eliminada — control remoto desactivado.")


def estado_dict() -> dict:
    """Estado completo serializable para el endpoint GET /kill-switch."""
    return {
        "active":                 _estado.activo,
        "fuente":                 _estado.fuente,
        "ts_ultima_verificacion": _estado.ts_verificacion,
        "gist_configurado":       bool(_gist_url),
        "gist_url":               _gist_url,
    }


# ── Descarga del Gist ──────────────────────────────────────────────────────────

def _fetch_sync(url: str) -> bool:
    """
    Descarga la URL del Gist de forma sincrona y retorna el campo 'active'.
    Usar dentro de asyncio.to_thread() para no bloquear el event loop.
    """
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        data = json.loads(resp.read())
    return bool(data.get("active", True))


async def verificar_gist() -> bool | None:
    """
    Consulta el Gist de forma asincrona.
    Retorna el nuevo estado (True/False), o None si la red fallo.
    En caso de fallo de red el estado anterior se conserva.
    """
    url = _gist_url
    if not url:
        return None

    try:
        nuevo = await asyncio.to_thread(_fetch_sync, url)
        _estado.activo          = nuevo
        _estado.fuente          = "gist"
        _estado.ts_verificacion = time.time()

        nivel = logging.INFO if nuevo else logging.WARNING
        logger.log(nivel, "Kill switch verificado", extra={"active": nuevo, "fuente": "gist"})
        if not nuevo:
            logger.warning("KILL SWITCH ACTIVADO — ejecucion de agentes bloqueada.")
        return nuevo

    except Exception as exc:
        _estado.fuente = "cache"
        logger.warning(
            "Kill switch — Gist inalcanzable; estado mantenido (%s). Causa: %s",
            _estado.activo, exc,
        )
        return None


def forzar_estado(activo: bool) -> None:
    """
    Fuerza el estado del kill switch manualmente.
    El monitor lo sobreescribirá en la próxima verificación del Gist (cada 5 min).
    Usar desde el endpoint POST /kill-switch/toggle.
    """
    _estado.activo          = activo
    _estado.fuente          = "manual"
    _estado.ts_verificacion = time.time()
    nivel = logging.INFO if activo else logging.WARNING
    logger.log(nivel, "Kill switch forzado a %s (manual).", "activo" if activo else "bloqueado")


async def iniciar_monitor(intervalo_s: float = _INTERVALO_S) -> None:
    """
    Tarea background: verifica el Gist periodicamente.
    Lanzar con asyncio.create_task(); se cancela limpiamente al salir.
    Si la URL cambia via set_gist_url(), la proxima iteracion la usa.
    """
    if not _gist_url:
        logger.info(
            "Kill switch: KILL_SWITCH_GIST_URL no configurada — "
            "control remoto desactivado (sistema siempre activo)."
        )

    logger.info("Kill switch monitor iniciado (intervalo=%ds).", int(intervalo_s))
    try:
        while True:
            if _gist_url:
                await verificar_gist()
            await asyncio.sleep(intervalo_s)
    except asyncio.CancelledError:
        logger.info("Kill switch monitor: tarea cancelada limpiamente.")
        raise
