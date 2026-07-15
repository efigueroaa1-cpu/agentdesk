"""
core/auth.py — Fachada de compatibilidad del motor de Autenticación JWT + RBAC.

Desde la migración hexagonal (ADR-0002) la implementación vive en:
  core/domain/user.py                    — jerarquía de roles, tiene_permiso, entidad User
  core/ports/auth_port.py                — interfaces AuthPort y UserRepositoryPort
  core/services/auth_service.py          — lógica de negocio (JWT, bcrypt, reglas CRUD)
  core/repositories/user_repository.py   — consultas SQLAlchemy a la tabla usuarios

Este módulo re-exporta la API histórica para no romper los puntos de uso
existentes (api.py, api_auth.py, test_security.py). Código nuevo debe
importar directamente del servicio: `from core.services import auth_service`.
"""
from __future__ import annotations

from core.domain.user import (  # noqa: F401
    JERARQUIA_ROLES as _JERARQUIA,
    RolType,
    SistemaNoConfiguradoError,
    tiene_permiso,
)
from core.services.auth_service import (  # noqa: F401
    JWT_ALGORITHM,
    TOKEN_EXPIRE_H,
    auth_service as _svc,
)

# ── API histórica de funciones de módulo (delegan en el servicio) ─────────────

def crear_token(username: str, role: str) -> dict:
    return _svc.crear_token(username, role)


def verificar_token(token: str) -> dict | None:
    return _svc.verificar_token(token)


def login(username: str, password: str) -> dict | None:
    return _svc.login(username, password)


def refrescar(refresh_token: str) -> dict | None:
    return _svc.refrescar(refresh_token)


def diagnostico_arranque(jwt_secret_path=None) -> dict:
    return _svc.diagnostico_arranque(jwt_secret_path)


def cambiar_password(username: str, nueva_password: str) -> bool:
    return _svc.cambiar_password(username, nueva_password)


def listar_usuarios() -> list[dict]:
    return _svc.listar_usuarios()


def crear_usuario(username: str, password_plain: str, rol: RolType = "viewer") -> dict:
    return _svc.crear_usuario(username, password_plain, rol)


def eliminar_usuario(username: str, solicitante: str) -> bool:
    return _svc.eliminar_usuario(username, solicitante)


def cambiar_rol(username: str, nuevo_rol: RolType) -> dict:
    return _svc.cambiar_rol(username, nuevo_rol)


def activar_desactivar(username: str, activo: bool) -> dict:
    return _svc.activar_desactivar(username, activo)


# ── Dependencia FastAPI (adaptador de entrada, no pertenece al servicio) ──────

def requiere_rol(rol_minimo: RolType):
    """
    Dependencia FastAPI que verifica el rol del token JWT.

    Uso:
        @app.delete("/usuarios/{id}")
        async def eliminar(req: Request, _=Depends(requiere_rol("admin"))):
            ...
    """
    from fastapi import Depends, HTTPException, Request

    async def _check(request: Request) -> dict:
        rol = getattr(request.state, "rol", None) or "viewer"
        sub = getattr(request.state, "usuario", None) or "anónimo"
        if not tiene_permiso(rol, rol_minimo):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Rol '{rol}' insuficiente. "
                    f"Se requiere '{rol_minimo}' o superior."
                ),
            )
        return {"username": sub, "rol": rol}

    return Depends(_check)
