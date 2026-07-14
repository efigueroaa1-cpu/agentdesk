"""
core/repositories/user_repository.py — Adaptador SQLAlchemy del
UserRepositoryPort. Todas las consultas a la tabla `usuarios` viven aquí;
el servicio de auth (core/services/auth_service.py) no conoce SQL.
"""
from __future__ import annotations

import logging

from core.domain.user import User
from core.timeutil import utcnow

logger = logging.getLogger(__name__)


def _a_dominio(u) -> User:
    """Mapea la fila ORM `Usuario` a la entidad pura `User`."""
    return User(
        id=u.id,
        username=u.username,
        rol=u.rol,
        activo=bool(u.activo),
        ts_creacion=u.ts_creacion,
        ultimo_acceso=u.ultimo_acceso,
        password_hash=u.password_hash or "",
    )


class SqlAlchemyUserRepository:
    """Implementación SQLAlchemy de core.ports.auth_port.UserRepositoryPort."""

    def contar(self) -> int:
        from core.database import Usuario, get_session
        with get_session() as s:
            return s.query(Usuario).count()

    def obtener_por_username(self, username: str, solo_activos: bool = False) -> User | None:
        from core.database import Usuario, get_session
        with get_session() as s:
            q = s.query(Usuario).filter_by(username=username)
            if solo_activos:
                q = q.filter_by(activo=True)
            u = q.first()
            return _a_dominio(u) if u else None

    def listar(self) -> list[User]:
        from core.database import Usuario, get_session
        with get_session() as s:
            return [_a_dominio(u) for u in s.query(Usuario).order_by(Usuario.id).all()]

    def agregar(self, username: str, password_hash: str, rol: str, activo: bool = True) -> User:
        from core.database import Usuario, get_session
        with get_session() as s:
            u = Usuario(
                username=username,
                password_hash=password_hash,
                rol=rol,
                activo=activo,
            )
            s.add(u)
            s.commit()
            return _a_dominio(u)

    def eliminar(self, username: str) -> bool:
        from core.database import Usuario, get_session
        with get_session() as s:
            u = s.query(Usuario).filter_by(username=username).first()
            if not u:
                return False
            s.delete(u)
            s.commit()
            return True

    def contar_admins_activos(self) -> int:
        from core.database import Usuario, get_session
        with get_session() as s:
            return s.query(Usuario).filter_by(rol="admin", activo=True).count()

    def actualizar_ultimo_acceso(self, username: str) -> None:
        from core.database import Usuario, get_session
        with get_session() as s:
            u = s.query(Usuario).filter_by(username=username).first()
            if u:
                u.ultimo_acceso = utcnow()
                s.commit()

    def actualizar_password_hash(self, username: str, password_hash: str) -> bool:
        from core.database import Usuario, get_session
        with get_session() as s:
            u = s.query(Usuario).filter_by(username=username).first()
            if not u:
                return False
            u.password_hash = password_hash
            s.commit()
            return True

    def actualizar_rol(self, username: str, rol: str) -> User:
        from core.database import Usuario, get_session
        with get_session() as s:
            u = s.query(Usuario).filter_by(username=username).first()
            if not u:
                raise ValueError(f"Usuario '{username}' no encontrado.")
            u.rol = rol
            s.commit()
            return _a_dominio(u)

    def actualizar_activo(self, username: str, activo: bool) -> User:
        from core.database import Usuario, get_session
        with get_session() as s:
            u = s.query(Usuario).filter_by(username=username).first()
            if not u:
                raise ValueError(f"Usuario '{username}' no encontrado.")
            u.activo = activo
            s.commit()
            return _a_dominio(u)
