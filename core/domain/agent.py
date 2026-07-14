"""
core/domain/agent.py — Entidad Agent pura (espejo de AgentConfig sin Pydantic).

AgentConfig (core/schemas.py) sigue siendo el modelo de validación del borde
HTTP; esta entidad es la representación interna sin dependencias de framework.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Agent:
    """Agente de IA configurado en el sistema."""
    id:          str
    nombre:      str
    tipo_ia:     str = ""
    modelo:      str = ""
    temperatura: float = 0.7
    idioma:      str = "es"
    area:        str = ""
    prompt_base: str = ""
    activo:      bool = True
    ubicacion:   dict | None = field(default=None)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "nombre":      self.nombre,
            "tipo_ia":     self.tipo_ia,
            "modelo":      self.modelo,
            "temperatura": self.temperatura,
            "idioma":      self.idioma,
            "area":        self.area,
            "prompt_base": self.prompt_base,
            "activo":      self.activo,
            "ubicacion":   self.ubicacion,
        }
