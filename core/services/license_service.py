"""
core/services/license_service.py — Licencia RSA local (Fase 24, ADR-0022).

Reemplaza el control de activacion remoto (Gist de GitHub, punto unico de
falla y URL de control externa) por una licencia LOCAL firmada con RSA y
vinculada al ID de hardware de la maquina. Cero red: la validacion es
criptografia pura sobre un archivo en disco.

Formato de license.key (JSON UTF-8):

    {
      "payload": {
        "machine_id": "<sha256 truncado del MachineGuid>",
        "emitida":    "2026-07-17",
        "expira":     "2027-07-17" | null,
        "edicion":    "gold",
        "cliente":    "Nombre"
      },
      "firma": "<base64 RSA-PSS-SHA256 del payload canonico>"
    }

El payload se canonicaliza con json.dumps(sort_keys=True,
separators=(",", ":")) antes de firmar/verificar — el orden de claves del
archivo no importa, la firma es sobre el contenido semantico.

La clave PUBLICA va embebida como constante del modulo (no como data file:
un .pem suelto seria la misma clase de fallo invisible-a-PyInstaller que
alembic.ini en la Fase 22). La clave PRIVADA vive fuera del repo
(%APPDATA%/AgentDesk/licensing/agentdesk_priv.pem en la maquina emisora)
y solo la usa scripts/generar_licencia.py.

Limite honesto (documentado en ADR-0022): esta licencia NO impide el
parcheo del propio binario — quien edita el exe puede saltarse cualquier
chequeo interno. La integridad del binario distribuido la da la firma de
codigo Authenticode (SignTool en build_all.ps1); la licencia RSA decide
si ESTA maquina esta autorizada a ejecutar agentes. Capas distintas.

Env vars:
    AGENTDESK_LICENSE_PUB  — ruta a un PEM publico alternativo (tests,
                             re-emision de claves). Sin definir: la
                             constante embebida.
    AGENTDESK_LICENSE_FILE — ruta alternativa a license.key (tests).
"""
from __future__ import annotations

import base64
import binascii
import datetime as _dt
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger(__name__)

# Clave publica del producto (RSA 3072). La privada NO esta en el repo.
CLAVE_PUBLICA_PEM = """-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEArfKiD9hK6DRn4XK95y9P
Me+ajTrgHRV2wVn5Jmbyo+GqO2wK5FnjNq6v4bNDlM9xFt50Pajvj4499AfhfdQj
Ms2A8vmAE0siNvlEM9oQ8bs5vsJ5rSvahsb/wLfMqpFVJTymR2d3LZTjOXz8uab7
Ut2WUNIj/PAgbN3qAdDQ/Vr9dFbGJw/54xMc9VYsUVX4/rCANGx+7AUhMAb98arv
4AAiS0kXWN3DGl+YIQpB+heCLPHE0W58tZeZfXYGFVR/OOHB6u8ZHFIOttvVkB8G
HFVNBcfcryXgFEbMKVTJqtTkpY2vxjt5JpHh2t4LehmPuchcA0Zn2OZ1DShkxtPz
wZxd4eAJ7EwGAvcQYwfpNhvyhq/9kasKHHeTN8GpI5qG5n/l4ZP4vX58wf/Qy9Cl
qLw8OHT6zxTYvc4QYuwFB/bX2gR0EzFa8dbiGD3HFITpbI0y8qUIf2OkMzIeYCXk
FMrSD8XO1FNfoqmV8eyWHIByE6eoWYjmArYoVXCTcqWpAgMBAAE=
-----END PUBLIC KEY-----
"""


# ── ID de hardware ─────────────────────────────────────────────────────────────

def machine_id() -> str:
    """
    ID estable de la maquina: sha256 del MachineGuid de Windows (registro,
    sobrevive a cambios de red/disco), truncado a 32 hex. Fallback fuera de
    Windows o sin registro: la MAC via uuid.getnode() (menos estable, pero
    determinista en la misma sesion de hardware).
    """
    crudo = ""
    try:
        import winreg  # noqa: cross-platform — solo Windows
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as k:
            crudo, _ = winreg.QueryValueEx(k, "MachineGuid")
    except Exception:
        crudo = f"mac:{uuid.getnode():012x}"
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:32]


# ── Canonicalizacion y firma ───────────────────────────────────────────────────

def _canonico(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def firmar_payload(payload: dict, privada_pem: bytes | str) -> str:
    """Firma el payload canonico con RSA-PSS-SHA256; retorna base64."""
    if isinstance(privada_pem, str):
        privada_pem = privada_pem.encode("utf-8")
    priv = serialization.load_pem_private_key(privada_pem, password=None)
    firma = priv.sign(
        _canonico(payload),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(firma).decode("ascii")


def generar_par_claves(bits: int = 3072) -> tuple[str, str]:
    """Par RSA efimero (privada_pem, publica_pem) — tests y self-check del gate."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return priv_pem, pub_pem


def _clave_publica():
    """PEM embebido, u override por archivo via AGENTDESK_LICENSE_PUB (tests)."""
    ruta = os.environ.get("AGENTDESK_LICENSE_PUB", "").strip()
    pem = Path(ruta).read_bytes() if ruta else CLAVE_PUBLICA_PEM.encode("ascii")
    return serialization.load_pem_public_key(pem)


def ruta_licencia() -> Path:
    ruta = os.environ.get("AGENTDESK_LICENSE_FILE", "").strip()
    if ruta:
        return Path(ruta)
    from core.path_manager import data_path
    return data_path("license.key")


# ── Validacion ─────────────────────────────────────────────────────────────────

def validar_licencia(contenido: str | None = None) -> dict:
    """
    Valida la licencia local. Sin tocar la red, nunca lanza.

    Retorna {"presente", "valida", "motivo", "payload"}:
      - sin archivo                 → presente=False, motivo="sin_licencia"
      - JSON corrupto / campos      → motivo="corrupta"
      - firma RSA invalida          → motivo="firma_invalida"
      - machine_id distinto         → motivo="otra_maquina"
      - fecha expira vencida        → motivo="expirada"
      - todo OK                     → valida=True, motivo="ok"

    Politica (ADR-0022, misma que Zero-Default): la AUSENCIA de licencia es
    un estado valido (modo desktop libre); una licencia PRESENTE pero
    invalida delata manipulacion y bloquea los agentes.
    """
    from core.telemetry_otel import medir_paso
    with medir_paso("license.validar"):
        return _validar_licencia(contenido)


def _validar_licencia(contenido: str | None) -> dict:
    if contenido is None:
        ruta = ruta_licencia()
        if not ruta.exists():
            return {"presente": False, "valida": False,
                    "motivo": "sin_licencia", "payload": None}
        try:
            contenido = ruta.read_text(encoding="utf-8")
        except OSError as exc:
            return {"presente": True, "valida": False,
                    "motivo": f"ilegible: {exc}", "payload": None}

    try:
        doc = json.loads(contenido)
        payload = doc["payload"]
        firma = base64.b64decode(doc["firma"])
        if not isinstance(payload, dict) or "machine_id" not in payload:
            raise KeyError("payload sin machine_id")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError,
            binascii.Error) as exc:
        return {"presente": True, "valida": False,
                "motivo": f"corrupta: {exc}", "payload": None}

    try:
        _clave_publica().verify(
            firma, _canonico(payload),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
    except (InvalidSignature, ValueError, OSError):
        return {"presente": True, "valida": False,
                "motivo": "firma_invalida", "payload": None}

    # Firma OK: el payload es autentico — ya se puede razonar sobre el.
    if payload["machine_id"] != machine_id():
        return {"presente": True, "valida": False,
                "motivo": "otra_maquina", "payload": payload}

    expira = payload.get("expira")
    if expira:
        try:
            if _dt.date.fromisoformat(expira) < _dt.date.today():
                return {"presente": True, "valida": False,
                        "motivo": "expirada", "payload": payload}
        except ValueError:
            return {"presente": True, "valida": False,
                    "motivo": "corrupta: fecha expira invalida", "payload": payload}

    return {"presente": True, "valida": True, "motivo": "ok", "payload": payload}


def guardar_licencia(contenido: str) -> dict:
    """
    Valida el contenido ANTES de escribirlo a license.key (nunca se persiste
    una licencia invalida). Retorna el veredicto de validar_licencia().
    """
    veredicto = validar_licencia(contenido)
    if veredicto["valida"]:
        ruta = ruta_licencia()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")
        logger.info("Licencia guardada en %s (edicion=%s, expira=%s)",
                    ruta, veredicto["payload"].get("edicion"),
                    veredicto["payload"].get("expira"))
    else:
        logger.warning("AUDITORIA_SEGURIDAD: intento de guardar licencia "
                       "invalida (motivo=%s) — rechazado sin escribir.",
                       veredicto["motivo"])
    return veredicto
