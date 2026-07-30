"""
core/key_vault.py — Gestion de API keys en tres niveles.

Prioridad de lectura (obtener_key):
  1. Windows Credential Manager (via keyring), si esta disponible.
  2. Vault cifrado local (.keyvault): AES-256-GCM con clave maestra derivada
     de ID de maquina + usuario del SO. Ilegible si se copia el archivo a
     otra maquina.
  3. Variable de entorno / .env (fallback secundario, texto plano).

El Credential Manager es el almacenamiento primario recomendado: no deja el
secreto en un archivo del perfil. keyring es opcional; si no esta instalado o
el SO no expone un backend (build headless, entorno sin sesion), la gestion
degrada a los niveles 2 y 3 sin interrumpir el arranque ni el Modo Faena.
"""
from __future__ import annotations
import base64
import hashlib
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_VAULT_FILE = None   # Se inicializa la primera vez que se usa

# ── Credential Manager del SO (keyring) ────────────────────────────────────────
# Nombre de servicio bajo el que se registran las keys en el Credential Manager
# de Windows. El "usuario" de cada credencial es el nombre de la variable
# (AGENTDESK_TAVILY_KEY, GROQ_API_KEY, GEMINI_API_KEY, ...).
_KEYRING_SERVICE = "AgentDesk"
_keyring_estado: bool | None = None   # None=sin probar; cachea el resultado


def _keyring():
    """Devuelve el modulo keyring si esta disponible y operativo, si no None.

    Deteccion best-effort y cacheada: en un entorno sin keyring o sin backend
    del SO, devuelve None una vez y no vuelve a intentarlo.
    """
    global _keyring_estado
    if _keyring_estado is False:
        return None
    try:
        import keyring
        from keyring.errors import KeyringError  # noqa: F401  (valida el backend)
        _keyring_estado = True
        return keyring
    except Exception:
        _keyring_estado = False
        return None


def _keyring_get(nombre_env: str) -> str | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(_KEYRING_SERVICE, nombre_env)
    except Exception as exc:
        logger.debug("keyring get '%s': %s", nombre_env, exc)
        return None


def _keyring_set(nombre_env: str, valor: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(_KEYRING_SERVICE, nombre_env, valor)
        return True
    except Exception as exc:
        logger.warning("keyring set '%s': %s", nombre_env, exc)
        return False


def _vault_path() -> Path:
    from core.path_manager import data_path
    return data_path("") / ".keyvault"


def _master_key() -> bytes:
    """Deriva la clave maestra desde el entorno de la máquina."""
    # Combinar: hostname + username + un salt fijo de la instalación
    import socket
    hostname = socket.gethostname()
    username = os.environ.get("USERNAME", os.environ.get("USER", "agentdesk"))

    # Salt de la instalación (se genera una vez y se guarda)
    salt_path = _vault_path().parent / ".install_salt"
    if salt_path.exists():
        salt = salt_path.read_bytes()
    else:
        import secrets
        salt = secrets.token_bytes(32)
        salt_path.parent.mkdir(parents=True, exist_ok=True)
        salt_path.write_bytes(salt)

    material = f"{hostname}:{username}".encode() + salt
    return hashlib.pbkdf2_hmac("sha256", material, salt, 100_000, dklen=32)


def cifrar(plaintext: str) -> str:
    """Cifra un string y devuelve base64 del ciphertext."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import secrets
        key    = _master_key()
        nonce  = secrets.token_bytes(12)
        ct     = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode()
    except ImportError:
        # Fallback: XOR simple con la clave (ofuscación, no cifrado fuerte)
        key    = _master_key()
        data   = plaintext.encode("utf-8")
        result = bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))
        return "xor:" + base64.b64encode(result).decode()
    except Exception as exc:
        logger.error("cifrar: %s", exc)
        return plaintext   # Fallback: sin cifrar


def descifrar(ciphertext: str) -> str:
    """Descifra un string cifrado con `cifrar()`."""
    if not ciphertext:
        return ""
    try:
        if ciphertext.startswith("xor:"):
            key    = _master_key()
            data   = base64.b64decode(ciphertext[4:])
            result = bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))
            return result.decode("utf-8")

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key   = _master_key()
        raw   = base64.b64decode(ciphertext)
        nonce = raw[:12]
        ct    = raw[12:]
        pt    = AESGCM(key).decrypt(nonce, ct, None)
        return pt.decode("utf-8")
    except Exception as exc:
        logger.warning("descifrar falló (%s) — devolviendo tal cual", exc)
        return ciphertext   # Puede ser un valor en texto plano (compatibilidad)


def guardar_key_cifrada(nombre_env: str, valor: str) -> bool:
    """Guarda una API key en el Credential Manager del SO (si esta disponible)
    y en el vault cifrado local. Se escriben ambos a proposito: el vault
    garantiza la lectura aunque el build no incluya keyring."""
    import json
    _keyring_set(nombre_env, valor)   # almacenamiento primario, best-effort
    vpath = _vault_path()
    vault: dict = {}
    if vpath.exists():
        try:
            vault = json.loads(vpath.read_text(encoding="utf-8"))
        except Exception:
            pass
    vault[nombre_env] = cifrar(valor)
    vpath.parent.mkdir(parents=True, exist_ok=True)
    vpath.write_text(json.dumps(vault, indent=2), encoding="utf-8")
    logger.info("Key cifrada guardada: %s", nombre_env)
    return True


def obtener_key(nombre_env: str) -> str | None:
    """Obtiene una API key con prioridad Credential Manager -> vault -> .env."""
    import json
    # 1. Windows Credential Manager (keyring), si esta disponible
    desde_keyring = _keyring_get(nombre_env)
    if desde_keyring:
        return desde_keyring
    # 2. Vault cifrado local (.keyvault)
    vpath = _vault_path()
    if vpath.exists():
        try:
            vault = json.loads(vpath.read_text(encoding="utf-8"))
            if nombre_env in vault:
                return descifrar(vault[nombre_env])
        except Exception:
            pass
    # 3. Fallback secundario: variable de entorno / .env
    return os.environ.get(nombre_env)


def migrar_env_a_vault() -> dict:
    """
    Lee el .env y migra las API keys al Credential Manager del SO y al vault
    cifrado (guardar_key_cifrada escribe en ambos). Idempotente: correr esto
    en cada arranque re-sincroniza sin duplicar.
    """
    from core.path_manager import data_path
    env_path = data_path("") / ".env"
    if not env_path.exists():
        return {"migradas": 0}

    claves_a_migrar = [
        "AGENTDESK_TAVILY_KEY",
        "GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
    ]
    migradas = 0
    for linea in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in linea: continue
        k, _, v = linea.partition("=")
        k = k.strip()
        v = v.strip()
        if k in claves_a_migrar and v:
            guardar_key_cifrada(k, v)
            migradas += 1
            # También poner en entorno actual
            os.environ[k] = v

    logger.info("Migración al vault: %d keys cifradas", migradas)
    return {"migradas": migradas}
