"""
core/domain/task.py — Entidad Task pura: una ejecución de trabajo de un agente.

Espejo sin SQLAlchemy de HistorialEjecucion (core/database.py); la capa
repositories/ hará el mapeo ORM ⇄ dominio cuando se migre ese módulo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Task:
    """Ejecución de una tarea por un agente, con resultado y métricas."""
    agente_id:     str
    tarea:         str
    exitoso:       bool = False
    duracion_s:    float = 0.0
    resumen:       str = ""
    agente_nombre: str = ""
    kpis:          dict = field(default_factory=dict)
    id:            int | None = None
    ts:            datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "agente_id":     self.agente_id,
            "agente_nombre": self.agente_nombre,
            "tarea":         self.tarea,
            "exitoso":       self.exitoso,
            "duracion_s":    self.duracion_s,
            "resumen":       self.resumen,
            "kpis":          self.kpis,
            "ts":            self.ts.isoformat() if self.ts else None,
        }
