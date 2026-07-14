"""
core/domain/user.py — Entidad User y reglas RBAC puras.

La jerarquía de roles y `tiene_permiso` viven aquí porque son reglas de
negocio: no dependen de HTTP, JWT ni SQL. Los adaptadores las consumen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

RolType = Literal["viewer", "supervisor", "admin"]

# Orden de roles: mayor índice = mayor privilegio
JERARQUIA_ROLES: dict[str, int] = {"viewer": 0, "supervisor": 1, "admin": 2}


def tiene_permiso(rol_usuario: str, rol_minimo: RolType) -> bool:
    """True si `rol_usuario` ≥ `rol_minimo` en la jerarquía RBAC."""
    return JERARQUIA_ROLES.get(rol_usuario, -1) >= JERARQUIA_ROLES.get(rol_minimo, 99)


class SistemaNoConfiguradoError(RuntimeError):
    """Lanzado cuando no existe users.json ni MASTER_PASSWORD_HASH."""


@dataclass
class User:
    """
    Usuario del sistema con rol RBAC.

    `password_hash` transporta SOLO el hash bcrypt (nunca texto plano) y se
    excluye siempre de `to_dict()` — ninguna representación pública lo expone.
    """
    username:      str
    rol:           str = "viewer"
    activo:        bool = True
    id:            int | None = None
    ts_creacion:   datetime | None = None
    ultimo_acceso: datetime | None = None
    password_hash: str = field(default="", repr=False)

    def es_admin(self) -> bool:
        return self.rol == "admin"

    def puede(self, rol_minimo: RolType) -> bool:
        return self.activo and tiene_permiso(self.rol, rol_minimo)

    def to_dict(self) -> dict:
        """Representación pública (idéntica al contrato histórico de la API)."""
        return {
            "id":            self.id,
            "username":      self.username,
            "rol":           self.rol,
            "activo":        self.activo,
            "ts_creacion":   self.ts_creacion.isoformat() if self.ts_creacion else None,
            "ultimo_acceso": self.ultimo_acceso.isoformat() if self.ultimo_acceso else None,
        }
