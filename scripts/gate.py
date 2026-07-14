# -*- coding: utf-8 -*-
"""
scripts/gate.py — Guardián de Arquitectura (ADR-0002).

Bloquea el avance (exit 1) si detecta:
  1. Etiquetas de deuda técnica pendiente (mismo patrón estricto que gate.ps1).
  2. Archivos fuente de más de 500 líneas. Los legados listados en
     LEGACY_OVERSIZE solo pueden DECRECER respecto a su línea base (trinquete);
     todo archivo nuevo debe nacer bajo el límite.
  3. Violaciones de imports entre capas hexagonales (domain/ports/services/
     repositories) — p.ej. un servicio importando de la capa api.
  4. Vulnerabilidades detectadas por Bandit (severidad media/alta en core,
     scripts y main.py).
  5. Fallas en el test-contrato de seguridad (tests/contract/test_auth_contract):
     ningún endpoint de escritura puede quedar sin JWT ni autorización explícita.

Uso:  python scripts/gate.py     (lo invoca gate.ps1 como paso de arquitectura)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

EXT_FUENTE = {".py", ".js", ".jsx", ".ps1", ".css", ".html"}
EXT_LIMITE = {".py", ".js", ".jsx"}
MAX_LINEAS = 500

# Se excluyen del escaneo de etiquetas porque definen el propio patrón.
EXCLUIR_TAGS = {"scripts/gate.py", "gate.ps1"}

# Patrón estricto case-sensitive (idéntico a gate.ps1): evita falsos positivos
# con la palabra española "todo" y con identificadores tipo "PatchB".
RE_TAGS = re.compile(r"(#|//|/\*|<!--)\s*(TODO|FIXME|PATCH)\b|\b(TODO|FIXME|PATCH):")

# Línea base de archivos legados >500 líneas (2026-07-14, conteo con líneas en
# blanco incluidas). Regla de trinquete: pueden bajar, nunca subir. Al bajar de
# 500 se retiran de esta lista.
LEGACY_OVERSIZE: dict[str, int] = {
    "agentdesk-dashboard/src/components/agents/AgentAreaView.jsx":       947,
    "agentdesk-dashboard/src/components/agents/AgentManager.jsx":        753,
    "agentdesk-dashboard/src/components/chat/ChatPanel.jsx":             684,
    "agentdesk-dashboard/src/components/hub/AgentHub.jsx":               553,
    "agentdesk-dashboard/src/components/hub/EmbeddingView3D.jsx":        634,
    "agentdesk-dashboard/src/components/hub/GanttModule.jsx":            569,
    "agentdesk-dashboard/src/components/pipeline/ErrorPanel.jsx":        553,
    "agentdesk-dashboard/src/components/pipeline/PipelineControl.jsx":  1050,
    "agentdesk-dashboard/src/components/proyectos/ProyectosModule.jsx": 1127,
    "agentdesk-dashboard/src/components/settings/SecurityPanel.jsx":     898,
    # api.py bajo 2865->1493 (2026-07-14, ADR-0003): trinquete apretado
    "core/api.py":                                                      1493,
    "core/orchestrator.py":                                             1215,
    # tools.py subio 1120->1153 (2026-07-14): evaluador AST que reemplaza eval()
    "core/tools.py":                                                    1153,
    # web_monitor.py subio 593->595 (2026-07-14): validacion de esquema http(s)
    "core/web_monitor.py":                                               595,
    "dashboard.py":                                                     1257,
    "ui/dashboard.py":                                                  1257,
}

# Reglas de capas (ADR-0002): prefijo de carpeta -> patrones de import prohibidos.
CAPA_API = re.compile(r"^\s*(from|import)\s+core\.(api|api_auth)\b")
FRAMEWORKS = re.compile(r"^\s*(from|import)\s+(fastapi|starlette)\b")
FRAMEWORKS_Y_ORM = re.compile(r"^\s*(from|import)\s+(fastapi|starlette|sqlalchemy|pydantic)\b")
CORE_NO_DOMAIN = re.compile(r"^\s*(from|import)\s+core\.(?!domain\b)\w+")
CORE_NO_DOMAIN_PORTS = re.compile(r"^\s*(from|import)\s+core\.(?!domain\b|ports\b)\w+")

REGLAS_IMPORTS: list[tuple[str, re.Pattern, str]] = [
    ("core/domain/",       CAPA_API,             "domain no puede importar la capa api"),
    ("core/domain/",       FRAMEWORKS_Y_ORM,     "domain debe ser puro (sin frameworks/ORM)"),
    ("core/domain/",       CORE_NO_DOMAIN,       "domain solo importa stdlib y core.domain"),
    ("core/ports/",        CAPA_API,             "ports no puede importar la capa api"),
    ("core/ports/",        FRAMEWORKS_Y_ORM,     "ports debe ser puro (sin frameworks/ORM)"),
    ("core/ports/",        CORE_NO_DOMAIN_PORTS, "ports solo importa stdlib, core.domain y core.ports"),
    ("core/services/",     CAPA_API,             "services NUNCA importa la capa api (ADR-0002)"),
    ("core/services/",     FRAMEWORKS,           "services no depende de FastAPI/Starlette"),
    ("core/repositories/", CAPA_API,             "repositories no puede importar la capa api"),
    ("core/repositories/", FRAMEWORKS,           "repositories no depende de FastAPI/Starlette"),
]


def inventario() -> list[str]:
    """Archivos versionados + nuevos sin ignorar (mismo criterio que gate.ps1)."""
    salida = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=RAIZ, capture_output=True, text=True, check=True,
    ).stdout
    return [f for f in salida.splitlines() if f and (RAIZ / f).is_file()]


def leer(rel: str) -> list[str]:
    try:
        return (RAIZ / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def check_tags(archivos: list[str]) -> list[str]:
    errores = []
    for rel in archivos:
        if Path(rel).suffix not in EXT_FUENTE or rel in EXCLUIR_TAGS:
            continue
        for n, linea in enumerate(leer(rel), 1):
            if RE_TAGS.search(linea):
                errores.append(f"  [TAG]     {rel}:{n}: {linea.strip()[:100]}")
    return errores


def check_tamano(archivos: list[str]) -> list[str]:
    errores = []
    for rel in archivos:
        if Path(rel).suffix not in EXT_LIMITE:
            continue
        lineas = len(leer(rel))
        if lineas <= MAX_LINEAS:
            continue
        base = LEGACY_OVERSIZE.get(rel)
        if base is None:
            errores.append(f"  [TAMANO]  {rel}: {lineas} lineas (max {MAX_LINEAS} para archivos nuevos)")
        elif lineas > base:
            errores.append(f"  [TAMANO]  {rel}: {lineas} lineas — CRECIO sobre su linea base legada ({base})")
    return errores


def check_imports(archivos: list[str]) -> list[str]:
    errores = []
    for rel in archivos:
        if not rel.endswith(".py"):
            continue
        reglas = [(p, r, m) for (p, r, m) in REGLAS_IMPORTS if rel.startswith(p)]
        if not reglas:
            continue
        for n, linea in enumerate(leer(rel), 1):
            for _, patron, motivo in reglas:
                if patron.search(linea):
                    errores.append(f"  [IMPORT]  {rel}:{n}: {linea.strip()[:80]}  <- {motivo}")
    return errores


def check_bandit() -> list[str]:
    """Análisis estático de vulnerabilidades (severidad media/alta)."""
    proc = subprocess.run(
        [sys.executable, "-m", "bandit", "-q", "-r", "core", "scripts", "main.py",
         "-ll", "--format", "custom",
         "--msg-template", "{severity} {test_id} {relpath}:{line} {msg}"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return []
    salida = (proc.stdout or proc.stderr or "bandit fallo sin salida").strip()
    return [f"  [BANDIT]  {linea}" for linea in salida.splitlines() if linea.strip()]


def check_contrato_auth() -> list[str]:
    """Test-contrato: toda escritura protegida por JWT o autorizada explícita."""
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.contract.test_auth_contract"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return []
    detalle = (proc.stderr or proc.stdout or "").strip().splitlines()[-25:]
    return ["  [CONTRATO] tests/contract/test_auth_contract.py FALLO:"] + \
           [f"    {linea}" for linea in detalle]


def main() -> int:
    archivos = inventario()
    print(f"Guardian de Arquitectura — {len(archivos)} archivos inventariados")

    errores = []
    errores += check_tags(archivos)
    errores += check_tamano(archivos)
    errores += check_imports(archivos)
    errores += check_bandit()
    errores += check_contrato_auth()

    if errores:
        print(f"\nVIOLACIONES ({len(errores)}):")
        for e in errores:
            print(e)
        print("\n=== ARQUITECTURA RECHAZADA ===")
        return 1

    print("OK: 0 etiquetas | 0 archivos nuevos >500 lineas | 0 violaciones de imports "
          "| bandit limpio (media/alta) | contrato de auth 100%")
    print("=== ARQUITECTURA APROBADA ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
