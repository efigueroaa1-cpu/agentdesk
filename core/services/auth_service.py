"""
core/services/auth_service.py — Servicio de Autenticación JWT + RBAC.

Lógica de negocio pura de auth (antes mezclada en core/auth.py): bcrypt,
emisión/verificación de JWT, reglas de gestión de usuarios (no eliminar el
último admin, longitudes mínimas, etc.). La persistencia llega inyectada
como UserRepositoryPort; el SQL vive en core/repositories/user_repository.py.

Flujo de arranque (sin cambios funcionales):
  1. Al primer login busca usuarios en la DB.
  2. Si la tabla está vacía, migra desde users.json (legacy).
  3. Si users.json tampoco existe, inicializa admin desde MASTER_PASSWORD_HASH.
  4. Sin MASTER_PASSWORD_HASH → SistemaNoConfiguradoError (503 en el borde).
"""
from __future__ import annotations

import json as _json
import logging
import os
from datetime import datetime, timedelta, timezone

from core.domain.user import (
    JERARQUIA_ROLES,
    RolType,
    SistemaNoConfiguradoError,
    tiene_permiso,
)
from core.ports.auth_port import UserRepositoryPort

logger = logging.getLogger(__name__)

JWT_ALGORITHM  = "HS256"
# ADR-0008: access token corto (reduce la ventana de ataque); la sesión se
# mantiene con refresh tokens rotativos persistidos (tabla refresh_tokens).
ACCESS_EXPIRE_MIN   = 30
REFRESH_EXPIRE_DIAS = 7
TOKEN_EXPIRE_H      = ACCESS_EXPIRE_MIN / 60   # alias histórico (fachada)

# Secretos débiles/conocidos que delatan una instalación manipulada
_SECRETOS_DEBILES = {"secret", "changeme", "default", "agentdesk", "123456",
                     "password", "admin", "jwt_secret", "dev"}


def _get_secret() -> str:
    """
    Clave JWT: AGENTDESK_JWT_SECRET (env var) tiene prioridad absoluta sobre
    jwt_secret.key. Sin la env var, se usa/genera el archivo persistido como
    hasta ahora (secreto aleatorio de 64 hex chars, escrito una sola vez).
    """
    _override = os.environ.get("AGENTDESK_JWT_SECRET", "").strip()
    if _override:
        return _override

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


class AuthService:
    """Implementación de core.ports.auth_port.AuthPort."""

    def __init__(self, repo: UserRepositoryPort | None = None):
        if repo is None:
            from core.repositories.user_repository import SqlAlchemyUserRepository
            repo = SqlAlchemyUserRepository()
        self._repo = repo

    # ── RBAC ──────────────────────────────────────────────────────────────

    def tiene_permiso(self, rol_usuario: str, rol_minimo: RolType) -> bool:
        return tiene_permiso(rol_usuario, rol_minimo)

    # ── Bootstrap ─────────────────────────────────────────────────────────

    def _inicializar_admin_db(self) -> None:
        """
        Inicializa la tabla usuarios si está vacía.
        Orden: DB → users.json → MASTER_PASSWORD_HASH en .env.
        """
        if self._repo.contar() > 0:
            return  # ya hay usuarios

        legacy = _cargar_desde_json()
        if legacy:
            migrados = 0
            for u in legacy:
                if not self._repo.obtener_por_username(u["username"]):
                    self._repo.agregar(
                        username=u["username"],
                        password_hash=u.get("password_hash", ""),
                        rol=u.get("role", u.get("rol", "viewer")),
                        activo=True,
                    )
                    migrados += 1
            logger.info("Migrados %d usuarios desde users.json a DB.", migrados)
            return

        master_hash = os.environ.get("MASTER_PASSWORD_HASH", "").strip()
        if not master_hash:
            raise SistemaNoConfiguradoError(
                "Sistema no configurado: la tabla de usuarios está vacía y "
                "MASTER_PASSWORD_HASH no está definido en .env. "
                "Agrega MASTER_PASSWORD_HASH=<bcrypt_hash> al .env y reinicia."
            )
        self._repo.agregar(
            username="admin", password_hash=master_hash, rol="admin", activo=True,
        )
        logger.info("Usuario admin inicializado desde MASTER_PASSWORD_HASH.")

    # ── JWT ───────────────────────────────────────────────────────────────

    def crear_token(self, username: str, role: str) -> dict:
        """Genera un token JWT firmado con los datos del usuario."""
        try:
            import jwt
            ahora   = datetime.now(timezone.utc)
            expira  = ahora + timedelta(minutes=ACCESS_EXPIRE_MIN)
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
                "expires_in": ACCESS_EXPIRE_MIN * 60,
            }
        except ImportError:
            # Fallback HMAC si PyJWT no está disponible
            import base64, hmac, hashlib
            payload = _json.dumps({"sub": username, "role": role}).encode()
            sig     = hmac.new(_get_secret().encode(), payload, hashlib.sha256).hexdigest()
            token   = base64.urlsafe_b64encode(payload).decode() + "." + sig
            return {"token": token, "username": username, "role": role,
                    "expires_in": ACCESS_EXPIRE_MIN * 60}

    def verificar_token(self, token: str) -> dict | None:
        """Decodifica y verifica el JWT. Devuelve el payload o None si es inválido."""
        if not token:
            return None
        try:
            import jwt
            return jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
        except ImportError:
            import base64, hmac, hashlib
            try:
                parts = token.split(".")
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

    # ── Operaciones de autenticación ──────────────────────────────────────

    def login(self, username: str, password: str) -> dict | None:
        """
        Autentica un usuario. Retorna el token JWT o None si las credenciales
        son incorrectas. Lanza SistemaNoConfiguradoError si la DB no tiene usuarios.
        """
        self._inicializar_admin_db()   # asegura que la DB tenga al menos el admin

        u = self._repo.obtener_por_username(username, solo_activos=True)
        if not u:
            return None
        if not _check_password(password, u.password_hash):
            return None
        self._repo.actualizar_ultimo_acceso(u.username)
        resultado = self.crear_token(u.username, u.rol)
        resultado["refresh_token"] = self._emitir_refresh(u.username)
        return resultado

    # ── Refresh tokens rotativos (ADR-0008) ───────────────────────────────

    @staticmethod
    def _hash_refresh(token: str) -> str:
        import hashlib
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _emitir_refresh(self, username: str) -> str:
        import secrets
        from datetime import timedelta as _td
        from core.repositories import refresh_token_repository as rt
        from core.timeutil import utcnow as _now
        token = secrets.token_urlsafe(48)
        rt.guardar(username, self._hash_refresh(token),
                   _now() + _td(days=REFRESH_EXPIRE_DIAS))
        return token

    def refrescar(self, refresh_token: str) -> dict | None:
        """
        Canjea un refresh token por un nuevo par access+refresh (rotación:
        el usado queda revocado). El reuso de un token ya revocado delata
        robo y revoca TODA la familia del usuario. Retorna None si inválido.
        """
        from core.repositories import refresh_token_repository as rt
        from core.timeutil import utcnow as _now

        if not refresh_token:
            return None
        h    = self._hash_refresh(refresh_token)
        fila = rt.obtener(h)
        if fila is None:
            return None
        if fila["revocado"]:
            n = rt.revocar_de_usuario(fila["username"])
            logger.warning(
                "AUDITORIA_SEGURIDAD: reuso de refresh token revocado — "
                "user_id=%s; %d tokens de la familia revocados (posible robo).",
                fila["username"], n,
            )
            return None
        if fila["expira"] < _now():
            return None

        rt.revocar(h)   # rotación: un solo uso
        u = self._repo.obtener_por_username(fila["username"], solo_activos=True)
        if not u:
            return None
        resultado = self.crear_token(u.username, u.rol)
        resultado["refresh_token"] = self._emitir_refresh(u.username)
        return resultado

    # ── Chequeo de salud de arranque (Fail-Hard, ADR-0008) ────────────────

    def diagnostico_arranque(self, jwt_secret_path=None) -> dict:
        """
        Salud de credenciales al arrancar:
          criticos → negarse a arrancar (secreto JWT débil = manipulación).
          modo_configuracion → arrancar degradado (instalación sin credenciales
          posibles: sin usuarios en DB y sin MASTER_PASSWORD_HASH en .env).

        AGENTDESK_JWT_SECRET (env var) tiene prioridad absoluta sobre
        jwt_secret.key: si está presente, se valida ESE valor y el archivo
        físico ni se lee (mismas reglas de fuerza — longitud/lista de débiles).
        """
        criticos: list[str] = []
        avisos:   list[str] = []

        _override = os.environ.get("AGENTDESK_JWT_SECRET", "").strip()
        if _override:
            if len(_override) < 32 or _override.lower() in _SECRETOS_DEBILES:
                criticos.append(
                    "JWT_SECRET debil o por defecto en AGENTDESK_JWT_SECRET: "
                    "usa un valor aleatorio de al menos 32 caracteres."
                )
        else:
            if jwt_secret_path is None:
                from core.path_manager import data_path
                jwt_secret_path = data_path("") / "jwt_secret.key"
            try:
                if jwt_secret_path.exists():
                    secreto = jwt_secret_path.read_text(encoding="utf-8").strip()
                    if len(secreto) < 32 or secreto.lower() in _SECRETOS_DEBILES:
                        criticos.append(
                            "JWT_SECRET debil o por defecto en jwt_secret.key: "
                            "elimina el archivo para regenerar uno aleatorio seguro."
                        )
            except OSError as e:
                avisos.append(f"No se pudo leer jwt_secret.key: {e}")

        try:
            sin_usuarios = self._repo.contar() == 0
        except Exception as e:
            sin_usuarios = False
            avisos.append(f"No se pudo consultar la tabla de usuarios: {e}")
        sin_master = not os.environ.get("MASTER_PASSWORD_HASH", "").strip()
        modo_config = sin_usuarios and sin_master
        if modo_config:
            avisos.append(
                "Sin usuarios en la base y sin MASTER_PASSWORD_HASH en .env: "
                "nadie puede iniciar sesion. Define MASTER_PASSWORD_HASH y reinicia."
            )

        return {"criticos": criticos, "avisos": avisos,
                "modo_configuracion": modo_config}

    def cambiar_password(self, username: str, nueva_password: str) -> bool:
        """Cambia la contraseña de un usuario con bcrypt. Sin texto plano."""
        if len(nueva_password.strip()) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres.")
        ok = self._repo.actualizar_password_hash(username, _hash_password(nueva_password))
        if ok:
            logger.info("Contraseña cambiada para usuario '%s'.", username)
        return ok

    # ── CRUD de usuarios (solo admin) ─────────────────────────────────────

    def listar_usuarios(self) -> list[dict]:
        """Devuelve todos los usuarios sin exponer el hash de contraseña."""
        self._inicializar_admin_db()
        return [u.to_dict() for u in self._repo.listar()]

    def crear_usuario(
        self, username: str, password_plain: str, rol: RolType = "viewer",
    ) -> dict:
        """
        Crea un nuevo usuario con bcrypt hash. Lanza ValueError si el username
        ya existe o la contraseña es demasiado corta.
        """
        if len(username.strip()) < 3:
            raise ValueError("El nombre de usuario debe tener al menos 3 caracteres.")
        if len(password_plain.strip()) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres.")
        if rol not in JERARQUIA_ROLES:
            raise ValueError(f"Rol inválido: '{rol}'. Opciones: {list(JERARQUIA_ROLES)}")

        self._inicializar_admin_db()
        if self._repo.obtener_por_username(username.strip()):
            raise ValueError(f"El usuario '{username}' ya existe.")
        u = self._repo.agregar(
            username=username.strip(),
            password_hash=_hash_password(password_plain),
            rol=rol,
            activo=True,
        )
        logger.info("Usuario '%s' creado con rol '%s'.", username, rol)
        return u.to_dict()

    def eliminar_usuario(self, username: str, solicitante: str) -> bool:
        """
        Elimina un usuario. No permite eliminar el propio usuario ni el último
        admin. `solicitante` es el username del admin que hace la petición.
        """
        if username == solicitante:
            raise ValueError("No puedes eliminar tu propio usuario.")

        u = self._repo.obtener_por_username(username)
        if not u:
            return False
        if u.rol == "admin" and self._repo.contar_admins_activos() <= 1:
            raise ValueError("No puedes eliminar el último administrador del sistema.")
        ok = self._repo.eliminar(username)
        if ok:
            logger.info("Usuario '%s' eliminado por '%s'.", username, solicitante)
        return ok

    def cambiar_rol(self, username: str, nuevo_rol: RolType) -> dict:
        """Cambia el rol de un usuario. Retorna el usuario actualizado."""
        if nuevo_rol not in JERARQUIA_ROLES:
            raise ValueError(f"Rol inválido: '{nuevo_rol}'. Opciones: {list(JERARQUIA_ROLES)}")

        u = self._repo.obtener_por_username(username)
        if not u:
            raise ValueError(f"Usuario '{username}' no encontrado.")
        if u.rol == "admin" and nuevo_rol != "admin":
            if self._repo.contar_admins_activos() <= 1:
                raise ValueError("No puedes degradar el último administrador.")
        actualizado = self._repo.actualizar_rol(username, nuevo_rol)
        logger.info("Rol de '%s' cambiado a '%s'.", username, nuevo_rol)
        return actualizado.to_dict()

    def activar_desactivar(self, username: str, activo: bool) -> dict:
        """Activa o desactiva un usuario."""
        u = self._repo.obtener_por_username(username)
        if not u:
            raise ValueError(f"Usuario '{username}' no encontrado.")
        if u.rol == "admin" and not activo:
            if self._repo.contar_admins_activos() <= 1:
                raise ValueError("No puedes desactivar el último administrador activo.")
        return self._repo.actualizar_activo(username, activo).to_dict()


# Instancia por defecto (misma semántica que las funciones de módulo históricas)
auth_service = AuthService()
