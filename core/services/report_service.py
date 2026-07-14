"""
core/services/report_service.py — Localización de reportes PDF (ADR-0003).

Búsqueda y listado de reportes generados por el pipeline en
%APPDATA%\\AgentDesk\\reportes. Sin FastAPI: retorna rutas/dicts y los 404
viajan como LookupError que el borde traduce.
"""
from __future__ import annotations

import re
from pathlib import Path


def _reportes_dir() -> Path:
    from core.path_manager import REPORTES_DIR
    return REPORTES_DIR


def _slug(texto: str) -> str:
    return texto.lower().replace(" ", "_").replace("-", "_")


def buscar_pdf(prefijo: str, agente_id: str) -> Path | None:
    """
    PDF más reciente con el prefijo dado para el agente
    (reporte_{slug}_{YYYYMMDD}_{HHMMSS}.pdf). Tolera ID crudo o slug.
    """
    slug    = _slug(agente_id)
    carpeta = _reportes_dir()
    if not carpeta.exists():
        return None
    patron  = re.compile(rf"^{re.escape(prefijo)}_{re.escape(slug)}_\d{{8}}_\d{{6}}\.pdf$")
    matches = [f for f in carpeta.iterdir() if patron.match(f.name)]
    return max(matches, key=lambda f: f.stat().st_mtime) if matches else None


def listar_todos() -> dict:
    """Todos los reportes (.pdf/.md/.json) ordenados por fecha descendente."""
    carpeta = _reportes_dir()
    if not carpeta.exists():
        return {"reportes": []}
    archivos = []
    for f in sorted(carpeta.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix in (".pdf", ".md", ".json"):
            archivos.append({
                "nombre":    f.name,
                "tipo":      f.suffix[1:],
                "tamano_kb": round(f.stat().st_size / 1024, 1),
                "mtime":     f.stat().st_mtime,
                "url":       f"/reportes/{f.name}",
            })
    return {"reportes": archivos[:50]}


def listar_por_agente(agente_id: str) -> dict:
    """PDFs del agente (éxito + correcciones), fecha descendente."""
    slug    = _slug(agente_id)
    carpeta = _reportes_dir()
    if not carpeta.exists():
        return {"agente": agente_id, "reportes": []}

    archivos = [
        {
            "nombre": f.name,
            "tipo":   "correccion" if f.name.startswith("correccion_") else "reporte",
            "mtime":  f.stat().st_mtime,
        }
        for f in carpeta.iterdir()
        if f.suffix == ".pdf" and slug in f.name
    ]
    archivos.sort(key=lambda x: x["mtime"], reverse=True)
    return {"agente": agente_id, "reportes": archivos}


def ruta_reporte(nombre: str) -> Path:
    """Ruta de un reporte por nombre. LookupError si no existe (404)."""
    archivo = _reportes_dir() / nombre
    if not archivo.exists() or not archivo.is_file():
        raise LookupError(f"Reporte '{nombre}' no encontrado.")
    return archivo
