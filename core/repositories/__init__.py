"""
core/repositories — Adaptadores de persistencia (SQLAlchemy).

Regla (ADR-0002): implementan los Protocol de core/ports devolviendo
entidades de core/domain. Único lugar (junto a core/database.py) donde
se permite tocar la sesión SQLAlchemy. Nunca importan de la capa api.
"""
from core.repositories.user_repository import SqlAlchemyUserRepository  # noqa: F401
