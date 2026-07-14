"""
core/updater.py — Sistema de auto-actualización de AgentDesk.

El archivo de versiones se puede alojar en cualquier URL accesible.
Por defecto usa GitHub Releases o un servidor local configurable.

Formato del manifest (version.json):
{
  "version": "1.1.0",
  "notas": "Correcciones de bugs y mejoras de rendimiento.",
  "url_descarga": "https://ejemplo.com/AgentDesk_1.1.0_x64-setup.exe",
  "fecha": "2026-06-26",
  "obligatoria": false
}
"""
from __future__ import annotations
import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime

logger = logging.getLogger(__name__)

VERSION_ACTUAL = "1.0.0"

# URL del manifest de versiones (configurable desde .env o settings)
DEFAULT_UPDATE_URL = os.environ.get(
    "AGENTDESK_UPDATE_URL",
    ""   # vacío = sin auto-update por defecto
)


def _comparar_versiones(v1: str, v2: str) -> int:
    """Compara versiones semánticas. Devuelve 1 si v1>v2, -1 si v1<v2, 0 si iguales."""
    def partes(v): return [int(x) for x in v.strip().split(".")[:3]]
    try:
        p1, p2 = partes(v1), partes(v2)
        return (p1 > p2) - (p1 < p2)
    except Exception:
        return 0


def verificar_actualizacion(url: str | None = None) -> dict:
    """
    Consulta el manifest de versiones y compara con la versión actual.

    Returns:
        {
          "disponible": bool,
          "version_actual": "1.0.0",
          "version_nueva": "1.1.0",    # si disponible
          "notas": "...",
          "url_descarga": "...",
          "obligatoria": False,
          "error": None                # o mensaje de error
        }
    """
    check_url = url or DEFAULT_UPDATE_URL
    resultado_base = {
        "disponible":     False,
        "version_actual": VERSION_ACTUAL,
        "version_nueva":  None,
        "notas":          "",
        "url_descarga":   "",
        "obligatoria":    False,
        "error":          None,
    }

    if not check_url:
        resultado_base["error"] = "URL de actualización no configurada."
        return resultado_base

    if not check_url.lower().startswith(("http://", "https://")):
        resultado_base["error"] = "URL de actualización con esquema no permitido (solo http/https)."
        return resultado_base

    try:
        req = urllib.request.Request(
            check_url,
            headers={"User-Agent": f"AgentDesk/{VERSION_ACTUAL}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - esquema validado arriba
            data = json.loads(resp.read().decode("utf-8"))

        version_nueva = data.get("version", "")
        if not version_nueva:
            resultado_base["error"] = "Manifest inválido: falta campo 'version'."
            return resultado_base

        hay_update = _comparar_versiones(version_nueva, VERSION_ACTUAL) > 0
        return {
            "disponible":     hay_update,
            "version_actual": VERSION_ACTUAL,
            "version_nueva":  version_nueva if hay_update else None,
            "notas":          data.get("notas", ""),
            "url_descarga":   data.get("url_descarga", ""),
            "obligatoria":    data.get("obligatoria", False),
            "fecha":          data.get("fecha", ""),
            "error":          None,
        }

    except urllib.error.URLError as exc:
        logger.warning("Updater: no se pudo conectar a %s: %s", check_url, exc)
        return {**resultado_base, "error": f"Sin conexión: {exc.reason}"}
    except json.JSONDecodeError:
        return {**resultado_base, "error": "Manifest con formato inválido."}
    except Exception as exc:
        return {**resultado_base, "error": str(exc)}


def guardar_url_update(url: str) -> bool:
    """Guarda la URL del servidor de actualizaciones en el .env."""
    try:
        from core.path_manager import data_path
        import pathlib
        env_path = pathlib.Path(os.environ.get("APPDATA", "")) / "AgentDesk" / ".env"
        if not env_path.exists():
            return False
        lines = env_path.read_text(encoding="utf-8").splitlines()
        found, new_lines = False, []
        for line in lines:
            if line.startswith("AGENTDESK_UPDATE_URL="):
                new_lines.append(f"AGENTDESK_UPDATE_URL={url}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"AGENTDESK_UPDATE_URL={url}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        os.environ["AGENTDESK_UPDATE_URL"] = url
        return True
    except Exception as exc:
        logger.error("guardar_url_update: %s", exc)
        return False
