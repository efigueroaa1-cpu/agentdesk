# -*- coding: utf-8 -*-
"""
scripts/check_deps.py — Validador de integridad de dependencias pre-build.

Objetivo (ADR-0028, endurecimiento de la cadena de suministro): antes de lanzar
build_all.ps1 (PyInstaller -> instalador), confirmar que el entorno Python tiene
EXACTAMENTE lo que el lockfile declara. Un desajuste silencioso aquí produce un
instalador que "compila" pero le falta un backend en runtime — el modo de fallo
más caro (p.ej. keyring/pywin32-ctypes ausentes => el .exe pierde el Windows
Credential Manager sin ningún error visible, exactamente el bug que este script
previene).

Qué valida:
  1. Cada pin `paquete==version` de requirements.txt está instalado con esa
     versión exacta (importlib.metadata sobre el entorno activo).
  2. Los paquetes CRÍTICOS para el instalador Windows (keyring, pywin32-ctypes,
     pyinstaller y el núcleo web) están presentes — se reportan aparte porque su
     ausencia rompe el empaquetado, no solo el runtime.
  3. Coherencia .in/.txt: cada nombre top-level de requirements.in aparece en el
     lockfile (evita el drift que dejó keyring fuera del .in en su día).

No instala nada, no toca secretos, no importa core/. Solo lee archivos y el
inventario de paquetes. Salida legible + exit code (0 OK / 1 problemas) para
encadenarlo en build_all.ps1 o en el gate.

Uso:
    python scripts/check_deps.py                # valida el entorno activo
    python scripts/check_deps.py --requirements otro.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REQ_TXT_DEFECTO = RAIZ / "requirements.txt"
REQ_IN = RAIZ / "requirements.in"

# Paquetes cuya ausencia rompe el INSTALADOR (no solo el runtime). Nombres
# normalizados (minúsculas, guion). pyinstaller solo se exige si está el spec.
CRITICOS_BUILD = {
    "keyring":         "Windows Credential Manager (core/key_vault.py, ADR-0028)",
    "pywin32-ctypes":  "backend keyring.backends.Windows del Credential Manager",
    "fastapi":         "núcleo web / API",
    "uvicorn":         "servidor ASGI del backend empaquetado",
    "cryptography":    "cifrado del vault local de API keys",
}

# ── Parseo de pins ──────────────────────────────────────────────────────────────

_RE_PIN = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._!+-]+)")
_RE_NOMBRE_IN = re.compile(r"^\s*([A-Za-z0-9._-]+)")


def _norm(nombre: str) -> str:
    """Normaliza un nombre de distribución (PEP 503): minúsculas, _/./- -> -."""
    return re.sub(r"[-_.]+", "-", nombre).lower()


def leer_pins(req_txt: Path) -> dict[str, str]:
    """Devuelve {nombre_normalizado: version} de las líneas `paquete==version`."""
    pins: dict[str, str] = {}
    for linea in req_txt.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        sin_comentario = linea.split("#", 1)[0]
        m = _RE_PIN.match(sin_comentario)
        if m:
            pins[_norm(m.group(1))] = m.group(2)
    return pins


def leer_nombres_in(req_in: Path) -> set[str]:
    """Nombres top-level declarados en requirements.in (ignora comentarios/vacías)."""
    nombres: set[str] = set()
    if not req_in.exists():
        return nombres
    for linea in req_in.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        s = linea.strip()
        if not s or s.startswith("#"):
            continue
        m = _RE_NOMBRE_IN.match(s)
        if m:
            nombres.add(_norm(m.group(1)))
    return nombres


def version_instalada(nombre_norm: str) -> str | None:
    """Versión instalada de una distribución, o None si no está en el entorno."""
    try:
        return metadata.version(nombre_norm)
    except metadata.PackageNotFoundError:
        return None


# ── Validaciones ────────────────────────────────────────────────────────────────

def validar(req_txt: Path) -> list[str]:
    """Corre las 3 validaciones y devuelve la lista de problemas (vacía = OK)."""
    problemas: list[str] = []

    if not req_txt.exists():
        return [f"[FALTA] lockfile no encontrado: {req_txt}"]

    pins = leer_pins(req_txt)

    # 1 + 2: cada pin instalado con la versión exacta; los críticos, aparte.
    faltantes_criticos: list[str] = []
    for nombre, version_pin in sorted(pins.items()):
        instalada = version_instalada(nombre)
        if instalada is None:
            msg = f"[NO-INSTALADO] {nombre}=={version_pin} declarado pero ausente del entorno"
            if nombre in CRITICOS_BUILD:
                faltantes_criticos.append(f"{msg}  <- CRÍTICO BUILD: {CRITICOS_BUILD[nombre]}")
            else:
                problemas.append(msg)
        elif instalada != version_pin:
            problemas.append(
                f"[DESAJUSTE] {nombre}: lockfile pide {version_pin}, instalado {instalada}")

    # Los críticos ausentes van primero (más graves).
    problemas = faltantes_criticos + problemas

    # 3: coherencia .in -> .txt (drift que dejó keyring fuera del .in).
    nombres_in = leer_nombres_in(REQ_IN)
    for nombre in sorted(nombres_in):
        if nombre not in pins and version_instalada(nombre) is None:
            problemas.append(
                f"[DRIFT-IN] {nombre} está en requirements.in pero no en el lockfile "
                f"ni instalado — re-corré pip-compile")

    return problemas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validador de integridad de dependencias pre-build.")
    parser.add_argument("--requirements", type=Path, default=REQ_TXT_DEFECTO,
                        help="Ruta al lockfile a validar (defecto: requirements.txt).")
    args = parser.parse_args(argv)

    print(f"Validador de dependencias — lockfile: {args.requirements}")
    problemas = validar(args.requirements)

    if problemas:
        print(f"\nPROBLEMAS ({len(problemas)}):")
        for p in problemas:
            print(f"  {p}")
        print("\n=== INTEGRIDAD DE DEPENDENCIAS RECHAZADA ===")
        return 1

    pins = leer_pins(args.requirements)
    criticos_ok = [n for n in CRITICOS_BUILD if n in pins]
    print(f"OK: {len(pins)} pins verificados | críticos de build presentes: "
          f"{', '.join(sorted(criticos_ok))}")
    print("=== INTEGRIDAD DE DEPENDENCIAS APROBADA ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
