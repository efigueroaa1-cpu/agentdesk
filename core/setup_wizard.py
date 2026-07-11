"""
setup_wizard: asistente de inicio y migración de configuración para AgentDesk.

Flujo en main.py:
  1. verificar_env()  →  si falta algo, ejecutar_wizard() y salir
  2. Si el .env existe pero es de una versión antigua, migrar_env() añade
     las variables nuevas sin borrar las credenciales del usuario.

El .env NUNCA se bundlea con el ejecutable — vive en %APPDATA%\\AgentDesk\\.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from core.path_manager import data_path

# ── Versión del esquema del .env ───────────────────────────────────────────────
# Incrementar este número cada vez que se añada o elimine una variable del .env.
# Cuando la versión del archivo del usuario no coincide, se ejecuta la migración.
ENV_VERSION_ACTUAL = 1

_ENV_PATH = data_path(".env")

# Variables obligatorias: (nombre, placeholder, descripción)
_VARIABLES_REQUERIDAS = [
    (
        "GEMINI_API_KEY",
        "TU_API_KEY_AQUI",
        "API Key de Google Gemini  →  https://aistudio.google.com/app/apikey",
    ),
    (
        "MASTER_PASSWORD_HASH",
        "TU_HASH_BCRYPT_AQUI",
        'Hash bcrypt de tu contrasena  →  python -c "import bcrypt; '
        'print(bcrypt.hashpw(b\'TuClave\', bcrypt.gensalt(12)).decode())"',
    ),
]

_ENV_TEMPLATE = f"""\
# AgentDesk — Configuracion de credenciales
# Version del esquema (no editar manualmente)
AGENTDESK_ENV_VERSION={ENV_VERSION_ACTUAL}

# API Key de Google Gemini (https://aistudio.google.com/app/apikey)
GEMINI_API_KEY=TU_API_KEY_AQUI

# Hash bcrypt de la contrasena de acceso al sistema.
# Genera con: python -c "import bcrypt; print(bcrypt.hashpw(b'TuClave', bcrypt.gensalt(12)).decode())"
MASTER_PASSWORD_HASH=TU_HASH_BCRYPT_AQUI
"""


# ── Lógica de verificación y migración ────────────────────────────────────────

def _leer_env() -> dict[str, str]:
    """Parsea el .env y devuelve un dict {CLAVE: valor}."""
    if not _ENV_PATH.exists():
        return {}
    resultado: dict[str, str] = {}
    for linea in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            clave, _, valor = linea.partition("=")
            resultado[clave.strip()] = valor.strip()
    return resultado


def env_configurado() -> bool:
    """
    Devuelve True si el .env existe, está en la versión correcta
    y todas las variables requeridas tienen valores reales (no placeholders).
    """
    if not _ENV_PATH.exists():
        return False
    valores = _leer_env()

    # Verificar versión del esquema
    version = int(valores.get("AGENTDESK_ENV_VERSION", "0"))
    if version < ENV_VERSION_ACTUAL:
        return False   # disparará migrar_env()

    # Verificar que cada variable requerida existe y no es placeholder
    for nombre, placeholder, _ in _VARIABLES_REQUERIDAS:
        valor = valores.get(nombre, "")
        if not valor or valor == placeholder:
            return False

    return True


def migrar_env() -> bool:
    """
    Detecta variables faltantes en un .env desactualizado y las añade
    SIN borrar las credenciales existentes del usuario.

    Devuelve True si la migración completó todo lo necesario,
    False si quedan variables sin configurar (requiere intervención manual).
    """
    valores    = _leer_env()
    contenido  = _ENV_PATH.read_text(encoding="utf-8")
    faltantes  = []

    for nombre, placeholder, _ in _VARIABLES_REQUERIDAS:
        if nombre not in valores:
            contenido += f"\n{nombre}={placeholder}\n"
            faltantes.append(nombre)

    # Actualizar la versión
    if "AGENTDESK_ENV_VERSION" not in valores:
        contenido = f"AGENTDESK_ENV_VERSION={ENV_VERSION_ACTUAL}\n" + contenido
    else:
        contenido = contenido.replace(
            f"AGENTDESK_ENV_VERSION={valores['AGENTDESK_ENV_VERSION']}",
            f"AGENTDESK_ENV_VERSION={ENV_VERSION_ACTUAL}",
        )

    _ENV_PATH.write_text(contenido, encoding="utf-8")

    if faltantes:
        _mostrar_aviso_migracion(faltantes)
        return False
    return True


def _mostrar_aviso_migracion(variables_nuevas: list[str]) -> None:
    sep = "=" * 62
    print(f"\n{sep}")
    print("  AGENTDESK — Actualizacion de configuracion requerida")
    print(sep)
    print()
    print("  Esta version de AgentDesk requiere variables nuevas")
    print("  en tu archivo de configuracion. Se han anadido con")
    print("  valores de ejemplo — debes rellenarlos antes de continuar.")
    print()
    for nombre in variables_nuevas:
        desc = next(d for n, _, d in _VARIABLES_REQUERIDAS if n == nombre)
        print(f"  → {nombre}")
        print(f"     {desc}")
        print()
    print(f"  Archivo: {_ENV_PATH}")
    print()
    abrir = input("  Abrir ahora con el editor? [S/n]: ").strip().lower()
    if abrir != "n":
        _abrir_editor(_ENV_PATH)
    print()
    print("  Reinicia AgentDesk cuando hayas guardado los cambios.")
    print(sep)
    sys.exit(0)


# ── Wizard de primer inicio ────────────────────────────────────────────────────

def ejecutar_wizard() -> None:
    """
    Crea el .env de plantilla en %APPDATA%\\AgentDesk\\ y guía al usuario.
    Termina el proceso hasta que el usuario configure sus credenciales.
    """
    sep = "=" * 62
    print(f"\n{sep}")
    print("  AGENTDESK — Primer inicio: configuracion requerida")
    print(sep)
    print()

    if not _ENV_PATH.exists():
        _ENV_PATH.write_text(_ENV_TEMPLATE, encoding="utf-8")
        print(f"  Archivo creado en:  {_ENV_PATH}")
        print()

    print("  Necesitas configurar los siguientes valores:")
    print()
    for i, (nombre, _, descripcion) in enumerate(_VARIABLES_REQUERIDAS, 1):
        print(f"  {i}. {nombre}")
        print(f"     {descripcion}")
        print()

    print("  Edita el archivo y reinicia AgentDesk.")
    print()
    abrir = input("  Abrir ahora con el editor? [S/n]: ").strip().lower()
    if abrir != "n":
        _abrir_editor(_ENV_PATH)

    print()
    print("  Reinicia AgentDesk cuando hayas guardado los cambios.")
    print(sep)
    sys.exit(0)


# ── Utilidad interna ───────────────────────────────────────────────────────────

def _abrir_editor(ruta: Path) -> None:
    """Abre el .env en el editor de texto predeterminado del sistema."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["notepad.exe", str(ruta)])
        elif sys.platform == "darwin":  # noqa: cross-platform
            subprocess.Popen(["open", "-t", str(ruta)])
        else:  # Linux  # noqa: cross-platform
            subprocess.Popen(["xdg-open", str(ruta)])
    except Exception:
        print(f"  No se pudo abrir el editor. Edita manualmente:\n  {ruta}")
