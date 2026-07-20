# -*- coding: utf-8 -*-
"""
scripts/verificar_cuotas_llm.py — Verificacion manual de cuota real de los
proveedores LLM, DESDE FUERA del binario empaquetado (2026-07-20).

No es parte de gate.ps1 ni de la suite automatica: hace llamadas REALES y
consume cuota real de cada proveedor (una respuesta minima por proveedor).
Correrlo manualmente cuando se sospecha saturacion (429) para confirmar si
la cuota diaria ya se reseteo, antes de lanzar una corrida completa de 22
agentes (Opcion 23) que la volveria a agotar en el primer intento.

Reusa core.providers.generate() -- el MISMO camino que usan los agentes en
produccion, para que el resultado sea representativo (nada de reimplementar
la llamada HTTP por separado, que podria dar un falso OK/FAIL).

Uso:
    python scripts/verificar_cuotas_llm.py
    python scripts/verificar_cuotas_llm.py --modelo groq:llama-3.3-70b-versatile
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Misma prioridad de .env que config_api.py (APPDATA primero, dev despues)
import config_api  # noqa: F401  (efecto secundario: load_dotenv)

MODELOS_DEFAULT = [
    "groq:llama-3.3-70b-versatile",   # 17 expertos ICI
    "groq:llama-3.1-8b-instant",      # 4 agentes de telemetria Modbus
    "gemini:models/gemini-2.5-flash", # U1 + fallback de la cadena
]

PROMPT_MINIMO = "Responde unicamente con la palabra OK."

_PATRON_TPD = re.compile(r"Used (\d+), Requested (\d+).*?Limit (\d+)", re.S)
_PATRON_TPD_ALT = re.compile(r"Limit (\d+), Used (\d+), Requested (\d+)", re.S)
_PATRON_GEMINI_QUOTA = re.compile(r"'quotaValue': '(\d+)'")


def _resumen_error(msg: str) -> str:
    """Extrae el dato de cuota util del error crudo del SDK, si esta presente."""
    m = _PATRON_TPD_ALT.search(msg)
    if m:
        limite, usado, pedido = m.groups()
        return f"cuota diaria de TOKENS: {usado}/{limite} usados (pedia {pedido} mas)"
    m = _PATRON_GEMINI_QUOTA.search(msg)
    if m:
        return f"cuota diaria de SOLICITUDES: limite={m.group(1)}/dia"
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "rate_limit" in msg.lower():
        return "429 generico (rate limit / cuota) sin detalle parseable"
    return msg[:160]


async def _probar(modelo: str) -> dict:
    # generate_con_uso() (no generate(), que solo devuelve el texto) — mismo
    # camino real que usan los agentes, con metadata de tokens/proveedor.
    from core.providers import generate_con_uso
    try:
        resultado = await generate_con_uso(modelo, PROMPT_MINIMO, temperature=0.0)
        return {"modelo": modelo, "ok": True,
                "detalle": resultado["texto"].strip()[:80]}
    except Exception as exc:
        return {"modelo": modelo, "ok": False, "detalle": _resumen_error(str(exc))}


async def _main(modelos: list[str]) -> int:
    print(f"Verificando {len(modelos)} modelo(s) via core.providers.generate() (llamada real)...\n")
    resultados = []
    for m in modelos:
        r = await _probar(m)
        resultados.append(r)
        icono = "OK " if r["ok"] else "FAIL"
        print(f"  [{icono}] {m}")
        print(f"         {r['detalle']}")

    ok = [r for r in resultados if r["ok"]]
    print(f"\n{len(ok)}/{len(resultados)} modelos respondieron con cuota disponible ahora mismo.")
    if not ok:
        print("Ningun proveedor tiene cuota libre todavia -- reintentar mas tarde "
              "(la Opcion 23 volvera a caer en Mock si se corre ahora).")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modelo", action="append", dest="modelos",
                    help="Modelo puntual a probar (repetible). Default: los 3 usados en produccion.")
    args = ap.parse_args()
    modelos = args.modelos or MODELOS_DEFAULT
    sys.exit(asyncio.run(_main(modelos)))


if __name__ == "__main__":
    main()
