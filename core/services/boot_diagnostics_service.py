"""
core/services/boot_diagnostics_service.py — Diagnóstico de Arranque
Enterprise (Fase 18, ADR-0016).

Unifica la validación de las variables de entorno críticas para un
despliegue de producción: AGENTDESK_JWT_SECRET y MASTER_PASSWORD_HASH
(reusa auth_service.diagnostico_arranque(), ADR-0008 — no se duplica esa
lógica) + AGENTDESK_DB_URL (nuevo en esta fase, política Zero-Default).

Política Zero-Default (ADR-0016): un secreto AUSENTE en un despliegue
desktop zero-config es una configuración VÁLIDA (SQLite sin credenciales,
JWT autogenerado en jwt_secret.key — ver ADR-0005/ADR-0008). Lo que nunca
es válido es un secreto PRESENTE con un valor por defecto/débil conocido:
eso delata una plantilla de despliegue copiada sin completar o una
instalación manipulada, y ahí sí se exige Fail-Hard (main.py aborta con
sys.exit(78) antes de levantar el servidor — ver core.auth.diagnostico_arranque
y su punto de invocación único en main.py).
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Mismo espíritu que RE_CRED_DEFECTO de scripts/gate.py (ADR-0008): un
# usuario/clave de base de datos tomado directo de un tutorial o de la
# plantilla del motor (postgres/root) es tan inseguro como no tener clave.
_CREDENCIALES_DB_DEBILES = {
    "", "changeme", "password", "admin", "admin123", "secret",
    "123456", "default", "letmein", "qwerty", "test", "postgres", "root",
}


def _validar_db_url() -> list[str]:
    """
    ADR-0016 [Zero-Default]: si AGENTDESK_DB_URL está definida y apunta a
    un motor de red (PostgreSQL), sus credenciales no pueden ser un
    usuario/clave por defecto conocido, ni tener la clave vacía, ni tener
    usuario == clave (credencial trivial).

    Sin AGENTDESK_DB_URL definida, o apuntando a sqlite:///: modo desktop
    válido por diseño (ADR-0005) — no es un crítico, no se evalúa.
    """
    db_url = os.environ.get("AGENTDESK_DB_URL", "").strip()
    if not db_url or db_url.startswith("sqlite"):
        return []
    if not db_url.startswith(("postgresql://", "postgresql+")):
        return []  # otro motor sin el patron usuario:clave@host que validamos aqui

    try:
        partes = urlsplit(db_url)
    except ValueError as exc:
        return [f"AGENTDESK_DB_URL no es una URL valida: {exc}"]

    usuario = (partes.username or "").lower()
    clave   = (partes.password or "").lower()

    if clave in _CREDENCIALES_DB_DEBILES:
        return [
            "AGENTDESK_DB_URL usa una credencial de base de datos por "
            "defecto o vacia — configura un usuario y clave dedicados "
            "antes de desplegar a produccion."
        ]
    if usuario and usuario == clave:
        return [
            "AGENTDESK_DB_URL usa el mismo valor para usuario y clave — "
            "credencial trivial, configura una clave distinta."
        ]
    return []


def diagnostico_arranque_sistema(jwt_secret_path=None) -> dict:
    """
    Diagnóstico de Arranque Enterprise: compone el chequeo de credenciales
    de auth_service (JWT/MASTER_PASSWORD_HASH, ADR-0008) con la validación
    nueva de AGENTDESK_DB_URL (ADR-0016). Firma y forma de retorno
    idénticas a core.auth.diagnostico_arranque() — {"criticos", "avisos",
    "modo_configuracion"} — para que el punto de invocación en main.py no
    cambie su lógica de Fail-Hard, solo la fuente de la que lee el veredicto.
    """
    from core.auth import diagnostico_arranque as _diag_auth
    from core.telemetry_otel import medir_paso

    with medir_paso("boot.diagnostico_arranque"):
        base = _diag_auth(jwt_secret_path)
        criticos_db = _validar_db_url()

    if criticos_db:
        logger.error(
            "DIAGNOSTICO_ARRANQUE: AGENTDESK_DB_URL con credenciales "
            "inseguras — %d hallazgo(s) critico(s)", len(criticos_db),
        )

    return {
        "criticos":           list(base["criticos"]) + criticos_db,
        "avisos":              list(base["avisos"]),
        "modo_configuracion":  base["modo_configuracion"],
    }
