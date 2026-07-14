"""
core/domain — Núcleo puro de la Arquitectura Hexagonal.

Regla (ADR-0002): este paquete NO importa FastAPI, SQLAlchemy ni ningún otro
módulo de core/. Solo stdlib. Las entidades son datos + reglas de negocio puras.
"""
from core.domain.user import (  # noqa: F401
    JERARQUIA_ROLES,
    RolType,
    SistemaNoConfiguradoError,
    User,
    tiene_permiso,
)
from core.domain.agent import Agent      # noqa: F401
from core.domain.task import Task        # noqa: F401
