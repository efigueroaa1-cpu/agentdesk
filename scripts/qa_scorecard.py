# -*- coding: utf-8 -*-
"""
scripts/qa_scorecard.py — QA Scorecard del build (Fase 28, ADR-0026).

Nota de veracidad: el pedido de la Fase 28 referenciaba "el QA Scorecard
de la Fase 26", pero ese artefacto nunca existio — se crea AQUI (misma
clase de discrepancia que las Fases 12/14/22, documentada en el ledger).

Genera qa_scorecard.json + qa_scorecard.md con el estado verificable del
build: veredicto del Guardian de Arquitectura, resultado de la suite
completa, soberania del lockfile (todo pineado ==) y presupuesto del
bundle inicial (<500 KB). Es el artefacto que el CI publica en cada run.

Uso: python scripts/qa_scorecard.py [--salida qa_scorecard.json]
Exit code 0 si TODOS los indicadores estan en verde; 1 si alguno fallo.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PRESUPUESTO_BUNDLE_KB = 500


def _gate() -> dict:
    proc = subprocess.run([sys.executable, "scripts/gate.py"],
                          cwd=RAIZ, capture_output=True, text=True)
    return {"aprobado": proc.returncode == 0,
            "resumen": (proc.stdout or "").strip().splitlines()[-1:]}


def _suite() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests",
         "-t", ".", "-p", "test_*.py"],
        cwd=RAIZ, capture_output=True, text=True)
    salida = proc.stderr or proc.stdout or ""
    m = re.search(r"Ran (\d+) tests", salida)
    skips = re.search(r"skipped=(\d+)", salida)
    return {"aprobada": proc.returncode == 0,
            "tests": int(m.group(1)) if m else 0,
            "skipped": int(skips.group(1)) if skips else 0}


def _lockfile() -> dict:
    """Soberania de suministro: cada dependencia del lockfile es exacta (==)."""
    sin_pin = []
    for linea in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines():
        limpia = linea.split("#")[0].strip()
        if not limpia:
            continue
        if "==" not in limpia:
            sin_pin.append(limpia)
    return {"soberano": not sin_pin, "dependencias_sin_pin": sin_pin}


def _bundle() -> dict:
    """Bundle inicial = assets referenciados por dist/index.html."""
    dist = RAIZ / "agentdesk-dashboard" / "dist"
    index = dist / "index.html"
    if not index.exists():
        return {"disponible": False,
                "nota": "sin dist/ en este entorno — el job frontend del CI lo mide"}
    activos = sorted(set(re.findall(r"assets/[\w.-]+\.(?:js|css)",
                                    index.read_text(encoding="utf-8"))))
    total_kb = round(sum((dist / a).stat().st_size for a in activos) / 1024, 1)
    return {"disponible": True, "inicial_kb": total_kb,
            "presupuesto_kb": PRESUPUESTO_BUNDLE_KB,
            "dentro_de_presupuesto": total_kb < PRESUPUESTO_BUNDLE_KB,
            "activos": activos}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="qa_scorecard.json")
    args = ap.parse_args()

    print("QA Scorecard — recolectando evidencia (gate + suite completa)...")
    scorecard = {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gate":     _gate(),
        "suite":    _suite(),
        "lockfile": _lockfile(),
        "bundle":   _bundle(),
    }
    verde = (scorecard["gate"]["aprobado"] and scorecard["suite"]["aprobada"]
             and scorecard["lockfile"]["soberano"]
             and scorecard["bundle"].get("dentro_de_presupuesto", True))
    scorecard["veredicto"] = "GOLD" if verde else "BLOQUEADO"

    ruta_json = RAIZ / args.salida
    ruta_json.write_text(json.dumps(scorecard, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    b = scorecard["bundle"]
    md = [
        f"# QA Scorecard — {scorecard['veredicto']}",
        f"Generado: {scorecard['generado']}",
        "",
        f"| Indicador | Estado |",
        f"|---|---|",
        f"| Guardian de Arquitectura | {'APROBADO' if scorecard['gate']['aprobado'] else 'RECHAZADO'} |",
        f"| Suite completa | {scorecard['suite']['tests']} tests — "
        f"{'OK' if scorecard['suite']['aprobada'] else 'FALLO'} "
        f"(skip: {scorecard['suite']['skipped']}) |",
        f"| Lockfile soberano | {'SI' if scorecard['lockfile']['soberano'] else 'NO'} |",
        f"| Bundle inicial | "
        + (f"{b['inicial_kb']} KB / {b['presupuesto_kb']} KB" if b.get("disponible")
           else "medido por el job frontend") + " |",
    ]
    ruta_json.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps(scorecard, indent=2, ensure_ascii=False))
    print(f"\nScorecard: {ruta_json} (+ .md) — veredicto: {scorecard['veredicto']}")
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
