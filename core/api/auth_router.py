"""
core/api/auth_router.py — Adaptador de entrada HTTP para Autenticación y RBAC.

Extraído originalmente de core/api.py como core/api_auth.py (migración
hexagonal, ADR-0002); reubicado a core/api/auth_router.py en la Fase 17
(ADR-0015) al convertir core/api.py en el paquete core/api/. Contenido y
comportamiento sin cambios respecto al core/api_auth.py anterior — mismo
router, mismo middleware, mismas rutas.

Contiene:
  - JWTMiddleware: decodifica el Bearer token y publica usuario/rol en
    request.state; exige token solo en mutaciones sensibles.
  - router: endpoints /auth/* (login, verificar, cambiar-password y CRUD
    de usuarios solo-admin). La lógica vive en core/services/auth_service.py;
    aquí solo se traduce HTTP ⇄ servicio.

core/api/__init__.py lo registra con app.add_middleware(JWTMiddleware) y
app.include_router(router) — mismas rutas y semántica que antes del split.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse as _JSONResponse

logger = logging.getLogger(__name__)

# ── Middleware JWT: verifica token en endpoints protegidos ─────────────────────

_RUTAS_PUBLICAS = {
    "/auth/login", "/health", "/auth/verificar",
    "/modelos", "/proveedores", "/docs", "/openapi.json",
    "/version", "/kill-switch",
}
# Prefijos públicos: accesibles sin token
_PREFIJOS_PUBLICOS = (
    "/ui/", "/ws/",
    "/monitor/", "/scheduler/",
    "/embeddings", "/historial", "/tendencias",
    "/reportes", "/uploads",
    "/agentes",       # lectura pública (escritura la protege el método HTTP)
    "/chat",          # el orquestador es la interfaz principal
    "/upload",        # subir archivos para analizar
    "/generar-pdf",   # generar reportes PDF
    "/backup/",       # backup/restore
    "/memoria/",      # memoria de conversaciones
    "/rate-limiter",  # estadísticas
    "/update/",       # verificar actualizaciones
    "/dashboard",     # dashboard analytics
    "/webhook/",      # webhooks externos (auth propia por bcrypt)
    "/finanzas/",     # motor financiero (auth por JWT del middleware global)
    "/gantt/",        # motor Gantt — CRUD de tareas y exportación PDF
    "/compliance/",   # auditoría de guardrails
    "/riesgo/",       # análisis de riesgo Gantt-Finanzas
    "/sistema/",      # KPIs maestros para BIDashboard
    "/analytics/",    # Curva S / EVM (rol supervisor+ verificado en endpoint)
    "/docs/",         # manual PDF (accesible a todos los usuarios autenticados)
    "/kill-switch/",  # toggle y URL del kill switch
)

# Solo proteger MUTACIONES sensibles con JWT
_METODOS_PROTEGIDOS = {"DELETE"}  # solo DELETE requiere siempre token
_RUTAS_SIEMPRE_PROTEGIDAS = {
    "/auth/cambiar-password",
    "/proveedores/apikey",
}


class JWTMiddleware(BaseHTTPMiddleware):
    """Verifica el JWT en todas las rutas protegidas."""

    async def dispatch(self, request: Request, call_next):
        path   = request.url.path
        method = request.method

        # OPTIONS siempre pasa (CORS preflight)
        if method == "OPTIONS":
            return await call_next(request)

        # Rutas explícitamente protegidas (siempre necesitan token)
        necesita_token = (
            path in _RUTAS_SIEMPRE_PROTEGIDAS
            or method in _METODOS_PROTEGIDOS
        )

        # Nota: las rutas bajo prefijos públicos (_RUTAS_PUBLICAS / _PREFIJOS_PUBLICOS)
        # no exigen token para pasar, pero si el cliente envía uno igual se decodifica
        # más abajo — varios endpoints bajo esos prefijos (p.ej. /analytics/, /backup/)
        # verifican el rol ellos mismos vía request.state.rol, y ese chequeo solo
        # funciona si el token llegó a decodificarse.
        auth_header = request.headers.get("Authorization", "")
        token       = auth_header.replace("Bearer ", "").strip()

        if not token:
            if necesita_token:
                return _JSONResponse(
                    status_code=401,
                    content={"detail": "Token requerido para esta operación."},
                )
            # Sin token: continúa como anónimo (rol por defecto "viewer" en cada endpoint)
            return await call_next(request)

        try:
            from core.auth import verificar_token
            datos = verificar_token(token)
            if datos:
                request.state.usuario = datos.get("sub")
                request.state.rol     = datos.get("role", "viewer")
        except Exception:
            pass

        return await call_next(request)


# ── Router /auth/* ─────────────────────────────────────────────────────────────

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str

class CambiarPasswordRequest(BaseModel):
    username:        str
    nueva_password:  str
    token:           str   # debe ser admin para cambiar cualquier usuario


@router.post("/auth/login")
async def auth_login(payload: LoginRequest) -> dict:
    """Autentica y devuelve un JWT. El frontend lo guarda y envía en cada request."""
    from core.auth import login as _login, SistemaNoConfiguradoError
    try:
        result = _login(payload.username, payload.password)
    except SistemaNoConfiguradoError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=401, detail="Credenciales incorrectas.")
    return result


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/auth/refresh")
async def auth_refresh(payload: RefreshRequest) -> dict:
    """
    Canjea un refresh token rotativo por un nuevo par access+refresh
    (ADR-0008). El access expira en 30 min; la sesión se mantiene por esta
    vía sin re-login. Token inválido/reusado → 401.
    """
    from core.auth import refrescar
    resultado = refrescar(payload.refresh_token)
    if resultado is None:
        raise HTTPException(status_code=401, detail="Refresh token inválido o expirado.")
    return resultado


@router.post("/auth/cambiar-password")
async def auth_cambiar_password(payload: CambiarPasswordRequest) -> dict:
    """Cambia la contraseña de un usuario (requiere token de admin)."""
    from core.auth import verificar_token, cambiar_password
    datos = verificar_token(payload.token)
    if not datos or datos.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Se requiere rol admin.")
    ok = cambiar_password(payload.username, payload.nueva_password)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Usuario '{payload.username}' no encontrado.")
    return {"ok": True, "mensaje": f"Contraseña de '{payload.username}' actualizada."}


@router.get("/auth/verificar")
async def auth_verificar(authorization: str = "") -> dict:
    """Verifica si un token es válido."""
    from core.auth import verificar_token
    token = authorization.replace("Bearer ", "").strip()
    datos = verificar_token(token)
    if not datos:
        raise HTTPException(status_code=401, detail="Token inválido o expirado.")
    return {"ok": True, "username": datos.get("sub"), "role": datos.get("role")}


# ── RBAC: Gestión de Usuarios (admin) ────────────────────────────────────────

class CrearUsuarioRequest(BaseModel):
    username:  str
    password:  str
    rol:       str = "viewer"

class CambiarRolRequest(BaseModel):
    nuevo_rol: str

class ActivarRequest(BaseModel):
    activo: bool


def exigir_admin_auditado(req: Request, accion: str, endpoint: str, log: logging.Logger) -> None:
    """
    RBAC + auditoría para operaciones críticas (patrón AUDITORIA_SEGURIDAD):
    403 con log WARNING si el rol no alcanza admin; log INFO si autoriza.
    Recibe el logger del módulo llamador para conservar el origen del log
    (los tests de seguridad y el análisis forense filtran por ese nombre).
    """
    rol     = getattr(req.state, "rol", "viewer")
    usuario = getattr(req.state, "usuario", None) or "anonimo"
    ip      = req.client.host if req.client else "desconocida"
    from core.auth import tiene_permiso
    if not tiene_permiso(rol, "admin"):
        log.warning(
            "AUDITORIA_SEGURIDAD: %s DENEGADA — user_id=%s rol=%s ip=%s endpoint='%s'",
            accion, usuario, rol, ip, endpoint,
        )
        raise HTTPException(403, detail="Se requiere rol admin.")
    log.info(
        "AUDITORIA_SEGURIDAD: %s AUTORIZADA — user_id=%s ip=%s",
        accion, usuario, ip,
    )


def _exigir_admin(req: Request) -> None:
    """403 si el rol del request no alcanza admin (deny-by-default: viewer)."""
    from core.auth import tiene_permiso
    if not tiene_permiso(getattr(req.state, "rol", "viewer"), "admin"):
        raise HTTPException(403, detail="Se requiere rol admin.")


@router.get("/auth/usuarios")
async def auth_listar_usuarios(req: Request) -> list[dict]:
    """Lista todos los usuarios del sistema. Solo admin."""
    from core.auth import listar_usuarios
    _exigir_admin(req)
    return listar_usuarios()


@router.post("/auth/usuarios")
async def auth_crear_usuario(req: Request, payload: CrearUsuarioRequest) -> dict:
    """Crea un nuevo usuario. Solo admin."""
    from core.auth import crear_usuario
    _exigir_admin(req)
    try:
        return crear_usuario(payload.username, payload.password, payload.rol)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@router.delete("/auth/usuarios/{username}")
async def auth_eliminar_usuario(username: str, req: Request) -> dict:
    """Elimina un usuario. Solo admin. No puede eliminar su propio usuario."""
    from core.auth import eliminar_usuario
    _exigir_admin(req)
    solicitante = getattr(req.state, "usuario", "")
    try:
        ok = eliminar_usuario(username, solicitante)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    if not ok:
        raise HTTPException(404, detail=f"Usuario '{username}' no encontrado.")
    return {"ok": True, "eliminado": username}


@router.put("/auth/usuarios/{username}/rol")
async def auth_cambiar_rol(username: str, payload: CambiarRolRequest, req: Request) -> dict:
    """Cambia el rol de un usuario. Solo admin."""
    from core.auth import cambiar_rol
    _exigir_admin(req)
    try:
        return cambiar_rol(username, payload.nuevo_rol)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@router.put("/auth/usuarios/{username}/activo")
async def auth_activar_usuario(username: str, payload: ActivarRequest, req: Request) -> dict:
    """Activa o desactiva un usuario. Solo admin."""
    from core.auth import activar_desactivar
    _exigir_admin(req)
    try:
        return activar_desactivar(username, payload.activo)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))
