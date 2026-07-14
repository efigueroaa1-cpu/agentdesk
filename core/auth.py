"""
core/auth.py — Motor de Autenticación JWT + RBAC.

Roles (jerarquía admin > supervisor > viewer):
  admin      — control total: crear/eliminar usuarios, kill switch, config global
  supervisor — ejecutar agentes, ver reportes, compliance, analytics
  viewer     — solo lectura: dashboards, historial, métricas

Flujo de arranque:
  1. Al primer login busca tabla `usuarios` en SQLite.
  2. Si la tabla existe pero está vacía, migra desde users.json (legacy).
  3. Si users.json tampoco existe, inicializa admin desde MASTER_PASSWORD_HASH en .env.
  4. Sin MASTER_PASSWORD_HASH → 503 para todos los intentos de login.

Seguridad:
  - Contraseñas almacenadas SOLO como bcrypt hash (nunca texto plano).
  - JWT firmado con clave aleatoria persistida en jwt_secret.key.
  - Permisos verificados por decorador `requiere_rol` en los endpoints.
"""
from __future__ import annotations

import json as _json
from core.timeutil import utcnow
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

JWT_ALGORITHM  = "HS256"
TOKEN_EXPIRE_H = 8

# Orden de roles: mayor índice = mayor privilegio
_JERARQUIA: dict[str, int] = {"viewer": 0, "supervisor": 1, "admin": 2}

RolType = Literal["viewer", "supervisor", "admin"]


# ── Clave JWT ──────────────────────────────────────────────────────────────────

def _get_secret() -> str:
    from core.path_manager import data_path
    secret_path = data_path("") / "jwt_secret.key"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    import secrets
    key = secrets.token_hex(32)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(key, encoding="utf-8")
    logger.info("JWT secret generado en %s", secret_path)
    return key


# ── RBAC: Jerarquía y permisos ────────────────────────────────────────────────

def tiene_permiso(rol_usuario: str, rol_minimo: RolType) -> bool:
    """True si `rol_usuario` ≥ `rol_minimo` en la jerarquía RBAC."""
    return _JERARQUIA.get(rol_usuario, -1) >= _JERARQUIA.get(rol_minimo, 99)


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


# ── Errores ───────────────────────────────────────────────────────────────────

class SistemaNoConfiguradoError(RuntimeError):
    """Lanzado cuando no existe users.json ni MASTER_PASSWORD_HASH."""


# ── Gestión de usuarios en DB ─────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    """Genera un bcrypt hash de la contraseña."""
    import bcrypt
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(plain: str, stored_hash: str) -> bool:
    """Verifica contraseña contra hash bcrypt."""
    try:
        import bcrypt
        return bcrypt.checkpw(plain.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception as e:
        logger.debug("bcrypt check error: %s", e)
        return False


def _cargar_desde_json() -> list[dict]:
    """Lee users.json (legado). Devuelve lista vacía si no existe."""
    from core.path_manager import data_path
    path = data_path("") / "users.json"
    if not path.exists():
        return []
    try:
        datos = _json.loads(path.read_text(encoding="utf-8"))
        for u in datos:
            u.pop("password_plain", None)
        return datos
    except Exception as e:
        logger.warning("Error leyendo users.json: %s", e)
        return []


def _inicializar_admin_db() -> None:
    """
    Inicializa la tabla usuarios si está vacía.
    Orden: DB → users.json → MASTER_PASSWORD_HASH en .env.
    """
    from core.database import Usuario, get_session

    with get_session() as s:
        total = s.query(Usuario).count()
        if total > 0:
            return  # ya hay usuarios

    # Migrar desde users.json si existe
    legacy = _cargar_desde_json()
    if legacy:
        with get_session() as s:
            for u in legacy:
                if not s.query(Usuario).filter_by(username=u["username"]).first():
                    s.add(Usuario(
                        username=u["username"],
                        password_hash=u.get("password_hash", ""),
                        rol=u.get("role", u.get("rol", "viewer")),
                        activo=True,
                    ))
            s.commit()
        logger.info("Migrados %d usuarios desde users.json a DB.", len(legacy))
        return

    # Inicializar admin desde MASTER_PASSWORD_HASH
    master_hash = os.environ.get("MASTER_PASSWORD_HASH", "").strip()
    if not master_hash:
        raise SistemaNoConfiguradoError(
            "Sistema no configurado: la tabla de usuarios está vacía y "
            "MASTER_PASSWORD_HASH no está definido en .env. "
            "Agrega MASTER_PASSWORD_HASH=<bcrypt_hash> al .env y reinicia."
        )
    with get_session() as s:
        s.add(Usuario(
            username="admin",
            password_hash=master_hash,
            rol="admin",
            activo=True,
        ))
        s.commit()
    logger.info("Usuario admin inicializado desde MASTER_PASSWORD_HASH.")


# ── JWT ───────────────────────────────────────────────────────────────────────

def crear_token(username: str, role: str) -> dict:
    """Genera un token JWT firmado con los datos del usuario."""
    try:
        import jwt
        ahora   = datetime.now(timezone.utc)
        expira  = ahora + timedelta(hours=TOKEN_EXPIRE_H)
        payload = {
            "sub":  username,
            "role": role,
            "iat":  ahora.timestamp(),
            "exp":  expira.timestamp(),
        }
        token = jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)
        return {
            "token":      token,
            "username":   username,
            "role":       role,
            "expires_in": TOKEN_EXPIRE_H * 3600,
        }
    except ImportError:
        # Fallback HMAC si PyJWT no está disponible
        import base64, hmac, hashlib
        payload = _json.dumps({"sub": username, "role": role}).encode()
        sig     = hmac.new(_get_secret().encode(), payload, hashlib.sha256).hexdigest()
        token   = base64.urlsafe_b64encode(payload).decode() + "." + sig
        return {"token": token, "username": username, "role": role,
                "expires_in": TOKEN_EXPIRE_H * 3600}


def verificar_token(token: str) -> dict | None:
    """Decodifica y verifica el JWT. Devuelve el payload o None si es inválido."""
    if not token:
        return None
    try:
        import jwt
        return jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
    except ImportError:
        import base64, hmac, hashlib
        try:
            parts   = token.split(".")
            if len(parts) < 2:
                return None
            payload = base64.urlsafe_b64decode(parts[0] + "==")
            ok      = hmac.compare_digest(
                parts[1],
                hmac.new(_get_secret().encode(), payload, hashlib.sha256).hexdigest(),
            )
            return _json.loads(payload) if ok else None
        except Exception:
            return None
    except Exception as e:
        logger.debug("Token inválido: %s", e)
        return None


# ── Operaciones de autenticación ──────────────────────────────────────────────

def login(username: str, password: str) -> dict | None:
    """
    Autentica un usuario.
    Retorna el token JWT o None si las credenciales son incorrectas.
    Lanza SistemaNoConfiguradoError si la DB no tiene usuarios.
    """
    _inicializar_admin_db()   # asegura que la DB tenga al menos el admin

    from core.database import Usuario, get_session
    with get_session() as s:
        u = s.query(Usuario).filter_by(username=username, activo=True).first()
        if not u:
            return None
        if not _check_password(password, u.password_hash):
            return None
        # Registrar último acceso
        u.ultimo_acceso = utcnow()
        s.commit()
        return crear_token(u.username, u.rol)


def cambiar_password(username: str, nueva_password: str) -> bool:
    """Cambia la contraseña de un usuario con bcrypt. Sin texto plano."""
    if len(nueva_password.strip()) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")

    from core.database import Usuario, get_session
    with get_session() as s:
        u = s.query(Usuario).filter_by(username=username).first()
        if not u:
            return False
        u.password_hash = _hash_password(nueva_password)
        s.commit()
    logger.info("Contraseña cambiada para usuario '%s'.", username)
    return True


# ── CRUD de usuarios (solo admin) ─────────────────────────────────────────────

def listar_usuarios() -> list[dict]:
    """Devuelve todos los usuarios sin exponer el hash de contraseña."""
    _inicializar_admin_db()
    from core.database import Usuario, get_session
    with get_session() as s:
        return [u.to_dict() for u in s.query(Usuario).order_by(Usuario.id).all()]


def crear_usuario(
    username: str,
    password_plain: str,
    rol: RolType = "viewer",
) -> dict:
    """
    Crea un nuevo usuario con bcrypt hash.
    Lanza ValueError si el username ya existe o la contraseña es demasiado corta.
    """
    if len(username.strip()) < 3:
        raise ValueError("El nombre de usuario debe tener al menos 3 caracteres.")
    if len(password_plain.strip()) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    if rol not in _JERARQUIA:
        raise ValueError(f"Rol inválido: '{rol}'. Opciones: {list(_JERARQUIA)}")

    from core.database import Usuario, get_session
    _inicializar_admin_db()
    with get_session() as s:
        if s.query(Usuario).filter_by(username=username.strip()).first():
            raise ValueError(f"El usuario '{username}' ya existe.")
        u = Usuario(
            username=username.strip(),
            password_hash=_hash_password(password_plain),
            rol=rol,
            activo=True,
        )
        s.add(u)
        s.commit()
        datos = u.to_dict()
    logger.info("Usuario '%s' creado con rol '%s'.", username, rol)
    return datos


def eliminar_usuario(username: str, solicitante: str) -> bool:
    """
    Elimina un usuario. No permite eliminar el propio usuario ni el último admin.
    `solicitante` es el username del admin que hace la petición.
    """
    if username == solicitante:
        raise ValueError("No puedes eliminar tu propio usuario.")

    from core.database import Usuario, get_session
    with get_session() as s:
        u = s.query(Usuario).filter_by(username=username).first()
        if not u:
            return False
        # No dejar la tabla sin admins
        if u.rol == "admin":
            n_admins = s.query(Usuario).filter_by(rol="admin", activo=True).count()
            if n_admins <= 1:
                raise ValueError("No puedes eliminar el último administrador del sistema.")
        s.delete(u)
        s.commit()
    logger.info("Usuario '%s' eliminado por '%s'.", username, solicitante)
    return True


def cambiar_rol(username: str, nuevo_rol: RolType) -> dict:
    """Cambia el rol de un usuario. Retorna el usuario actualizado."""
    if nuevo_rol not in _JERARQUIA:
        raise ValueError(f"Rol inválido: '{nuevo_rol}'. Opciones: {list(_JERARQUIA)}")

    from core.database import Usuario, get_session
    with get_session() as s:
        u = s.query(Usuario).filter_by(username=username).first()
        if not u:
            raise ValueError(f"Usuario '{username}' no encontrado.")
        # Evitar dejar sin admins
        if u.rol == "admin" and nuevo_rol != "admin":
            n_admins = s.query(Usuario).filter_by(rol="admin", activo=True).count()
            if n_admins <= 1:
                raise ValueError("No puedes degradar el último administrador.")
        u.rol = nuevo_rol
        s.commit()
        datos = u.to_dict()
    logger.info("Rol de '%s' cambiado a '%s'.", username, nuevo_rol)
    return datos


def activar_desactivar(username: str, activo: bool) -> dict:
    """Activa o desactiva un usuario."""
    from core.database import Usuario, get_session
    with get_session() as s:
        u = s.query(Usuario).filter_by(username=username).first()
        if not u:
            raise ValueError(f"Usuario '{username}' no encontrado.")
        if u.rol == "admin" and not activo:
            n_activos = s.query(Usuario).filter_by(rol="admin", activo=True).count()
            if n_activos <= 1:
                raise ValueError("No puedes desactivar el último administrador activo.")
        u.activo = activo
        s.commit()
        datos = u.to_dict()
    return datos
