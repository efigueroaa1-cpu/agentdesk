"""
path_manager: gestión unificada de rutas para AgentDesk.

Separa dos tipos de rutas:

  resource_path(rel)  — archivos de solo lectura que se BUNDLEAN con el exe
                        (config.json, data/datos_trabajo.json, etc.)
                        En desarrollo  → raíz del proyecto
                        En PyInstaller → sys._MEIPASS (carpeta temporal de extracción)

  data_path(rel)      — archivos de lectura/escritura generados en ejecución
                        (logs/, reportes/)
                        Siempre en %APPDATA%\\AgentDesk  (Windows)
                        o         ~/.agentdesk           (macOS/Linux)
                        Nunca dentro del ejecutable — el usuario puede acceder a ellos.

Importar en cualquier módulo que necesite una ruta:

    from core.path_manager import resource_path, data_path

    config = resource_path("config.json")          # Path objeto
    log    = data_path("logs/sistema.log")          # Path objeto, dirs creados
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Raíz del proyecto en desarrollo ───────────────────────────────────────────
# __file__ está en <raíz>/core/path_manager.py → dos niveles arriba = raíz
_DEV_ROOT = Path(__file__).resolve().parent.parent


# ── Recursos bundleados ────────────────────────────────────────────────────────

def resource_path(relative_path: str) -> Path:
    """
    Devuelve la ruta absoluta a un recurso de solo lectura.

    - Desarrollo  (script):    <raíz_proyecto>/<relative_path>
    - Producción  (PyInstaller): sys._MEIPASS/<relative_path>

    Uso:
        cfg = resource_path("config.json")
        dat = resource_path("datos_trabajo.json")
    """
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller extrae los archivos bundleados aquí
        base = Path(sys._MEIPASS)
    else:
        base = _DEV_ROOT
    return base / relative_path


# ── Datos de usuario (lectura/escritura) ──────────────────────────────────────

def _app_data_root() -> Path:
    """
    Devuelve la carpeta raíz de datos del usuario para AgentDesk.
    Crea la carpeta si no existe.

    Windows  : %APPDATA%\\AgentDesk
    macOS    : ~/Library/Application Support/AgentDesk
    Linux    : ~/.agentdesk
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "AgentDesk"
    elif sys.platform == "darwin":  # noqa: cross-platform
        base = Path.home() / "Library" / "Application Support" / "AgentDesk"
    else:  # Linux / noqa: cross-platform
        base = Path.home() / ".agentdesk"
    base.mkdir(parents=True, exist_ok=True)
    return base


def data_path(relative_path: str) -> Path:
    """
    Devuelve la ruta absoluta a un archivo de datos del usuario.
    Crea todos los directorios intermedios automáticamente.

    Uso:
        log     = data_path("logs/sistema.log")
        reporte = data_path("reportes/reporte_agente_20260617.md")
    """
    full = _app_data_root() / relative_path
    full.parent.mkdir(parents=True, exist_ok=True)
    return full


# ── config.json: Soberanía de Datos (2026-07-20) ──────────────────────────────

def config_path() -> Path:
    """
    Ruta ESCRIBIBLE de config.json — nunca vive dentro del binario.

    Prioridad 1: %APPDATA%\\AgentDesk\\config.json (ya inicializado o editado
    por el usuario — jamás se sobreescribe si existe).
    Si no existe, se bootstrapea UNA sola vez copiando la plantilla de solo
    lectura empaquetada con el exe (resource_path) — mismo patrón que
    .env/env.example en config_api.py. Así una reinstalación/actualización
    del .exe nunca pisa los agentes/prompts que el usuario personalizó, y
    restaurar_backup() (que ya escribía config.json en data_path) deja de ser
    una escritura muerta que nadie volvía a leer.
    """
    destino = data_path("config.json")
    if not destino.exists():
        plantilla = resource_path("config.json")
        if plantilla.exists():
            import shutil
            shutil.copy(plantilla, destino)
    return destino


# ── Constantes de rutas de uso frecuente ──────────────────────────────────────

LOG_PATH      = data_path("logs/sistema.log")
REPORTES_DIR  = data_path("reportes")  # directorio base, sin archivo
