"""
core/backup.py — Backup y restore de la base de datos y configuración.

Genera un ZIP con:
  - agentdesk.db        (base de datos SQLite)
  - config.json         (configuración de agentes)
  - .keyvault           (API keys cifradas)
  - uploads/            (archivos subidos por el usuario)
  - scheduler_config.json

El ZIP NO incluye:
  - .env (contiene contraseñas en texto)
  - logs/ (grandes y no críticos)
"""
from __future__ import annotations
import io
from core.timeutil import utcnow
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def crear_backup() -> bytes:
    """Crea un ZIP de backup y devuelve sus bytes."""
    from core.path_manager import data_path, resource_path

    buf     = io.BytesIO()
    ts      = utcnow().strftime("%Y%m%d_%H%M%S")
    version = _version()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Metadatos del backup
        meta = {
            "version":     version,
            "ts":          ts,
            "app":         "AgentDesk",
        }
        zf.writestr("backup_info.json", json.dumps(meta, indent=2))

        base = data_path("")   # %APPDATA%\AgentDesk

        # SQLite
        db = base / "agentdesk.db"
        if db.exists():
            zf.write(db, "agentdesk.db")
            logger.info("Backup: agentdesk.db incluida")

        # Vault de keys
        vault = base / ".keyvault"
        if vault.exists():
            zf.write(vault, ".keyvault")

        # Salt de instalación
        salt = base / ".install_salt"
        if salt.exists():
            zf.write(salt, ".install_salt")

        # Scheduler config
        sch = base / "scheduler_config.json"
        if sch.exists():
            zf.write(sch, "scheduler_config.json")

        # Pipeline config
        pipe = base / "pipeline_config.json"
        if pipe.exists():
            zf.write(pipe, "pipeline_config.json")

        # Users
        users = base / "users.json"
        if users.exists():
            zf.write(users, "users.json")

        # Config de agentes (desde _internal)
        try:
            cfg = resource_path("config.json")
            if cfg.exists():
                zf.write(cfg, "config.json")
        except Exception:
            pass

        # Uploads (archivos subidos por el usuario)
        uploads = base / "uploads"
        if uploads.exists():
            for f in uploads.rglob("*"):
                if f.is_file():
                    zf.write(f, f"uploads/{f.name}")
            logger.info("Backup: %d uploads incluidos", len(list(uploads.glob("*"))))

    logger.info("Backup creado: %d bytes", buf.tell())
    buf.seek(0)
    return buf.getvalue()


def restaurar_backup(zip_bytes: bytes) -> dict:
    """
    Restaura un backup desde un ZIP.
    Devuelve {"ok": True, "restaurados": [...]} o {"ok": False, "error": "..."}
    """
    from core.path_manager import data_path
    base = data_path("")

    try:
        buf  = io.BytesIO(zip_bytes)
        restaurados = []

        with zipfile.ZipFile(buf, "r") as zf:
            nombres = zf.namelist()

            # Verificar que es un backup de AgentDesk
            if "backup_info.json" not in nombres:
                return {"ok": False, "error": "El archivo no es un backup válido de AgentDesk."}

            meta = json.loads(zf.read("backup_info.json"))
            logger.info("Restaurando backup v%s de %s", meta.get("version"), meta.get("ts"))

            for nombre in nombres:
                if nombre == "backup_info.json": continue
                try:
                    data = zf.read(nombre)
                    dest = base / nombre
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    restaurados.append(nombre)
                except Exception as exc:
                    logger.warning("Restore: no se pudo restaurar '%s': %s", nombre, exc)

        return {
            "ok":         True,
            "restaurados":restaurados,
            "total":      len(restaurados),
            "version_backup": meta.get("version"),
            "fecha_backup":   meta.get("ts"),
        }
    except zipfile.BadZipFile:
        return {"ok": False, "error": "El archivo ZIP está corrupto."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _version() -> str:
    """Lee la versión del archivo version_info.txt o devuelve fallback."""
    try:
        from core.path_manager import resource_path
        vpath = resource_path("version_info.txt")
        if vpath.exists():
            for line in vpath.read_text().splitlines():
                if "FileVersion" in line or "ProductVersion" in line:
                    return line.split(",")[0].split("(")[-1].strip().strip("'\"")
    except Exception:
        pass
    return "0.3.0"
