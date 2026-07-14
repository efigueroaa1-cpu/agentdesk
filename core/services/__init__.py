"""
core/services — Lógica de negocio desacoplada (Arquitectura Hexagonal).

Regla (ADR-0002): los servicios dependen de core/domain y core/ports
(y de los repositorios vía inyección). PROHIBIDO importar core.api,
core.api_auth, FastAPI o Starlette desde esta capa — scripts/gate.py
bloquea cualquier violación.
"""
from core.services.auth_service import AuthService, auth_service  # noqa: F401
