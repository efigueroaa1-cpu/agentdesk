# -*- coding: utf-8 -*-
"""
scripts/generar_licencia.py — Emisor de licencias RSA (Fase 24, ADR-0022).

Herramienta del EMISOR (no se distribuye al cliente). Usa la clave privada
que vive FUERA del repo:

    %APPDATA%/AgentDesk/licensing/agentdesk_priv.pem

Uso:
    python scripts/generar_licencia.py --machine-id <id> [--dias 365]
        [--edicion gold] [--cliente "Nombre"] [--salida license.key]

    # El machine_id de la maquina destino se obtiene alli con:
    python -c "from core.services.license_service import machine_id; print(machine_id())"
    # o en la UI: SecurityPanel -> Kill Switch -> Instalar licencia.

    # Regenerar el par de claves (invalida TODAS las licencias emitidas;
    # exige actualizar CLAVE_PUBLICA_PEM en core/services/license_service.py):
    python scripts/generar_licencia.py --generar-claves
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.services import license_service  # noqa: E402


def _ruta_privada() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home())) / "AgentDesk" / "licensing"
    return base / "agentdesk_priv.pem"


def _generar_claves() -> int:
    ruta = _ruta_privada()
    if ruta.exists():
        print(f"ERROR: {ruta} ya existe. Borra el archivo a mano si de verdad "
              "quieres regenerar (invalida todas las licencias emitidas).")
        return 1
    priv, pub = license_service.generar_par_claves()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(priv, encoding="ascii")
    print(f"Clave privada guardada en: {ruta}")
    print("Pega esta clave publica en CLAVE_PUBLICA_PEM "
          "(core/services/license_service.py):\n")
    print(pub)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Emisor de licencias AgentDesk")
    ap.add_argument("--generar-claves", action="store_true",
                    help="genera un par RSA nuevo (la privada fuera del repo)")
    ap.add_argument("--machine-id", help="ID de hardware de la maquina destino")
    ap.add_argument("--dias", type=int, default=365,
                    help="vigencia en dias (0 = perpetua)")
    ap.add_argument("--edicion", default="gold")
    ap.add_argument("--cliente", default="")
    ap.add_argument("--salida", default="license.key")
    args = ap.parse_args()

    if args.generar_claves:
        return _generar_claves()

    if not args.machine_id:
        ap.error("--machine-id es obligatorio (o usa --generar-claves)")

    ruta_priv = _ruta_privada()
    if not ruta_priv.exists():
        print(f"ERROR: no existe la clave privada del emisor ({ruta_priv}). "
              "Ejecuta --generar-claves primero.")
        return 1

    hoy = _dt.date.today()
    payload = {
        "machine_id": args.machine_id.strip(),
        "emitida":    hoy.isoformat(),
        "expira":     (hoy + _dt.timedelta(days=args.dias)).isoformat()
                      if args.dias > 0 else None,
        "edicion":    args.edicion,
        "cliente":    args.cliente,
    }
    firma = license_service.firmar_payload(payload, ruta_priv.read_bytes())
    doc = json.dumps({"payload": payload, "firma": firma}, indent=2)

    Path(args.salida).write_text(doc, encoding="utf-8")
    print(f"Licencia emitida: {args.salida}")
    print(f"  machine_id: {payload['machine_id']}")
    print(f"  edicion:    {payload['edicion']}")
    print(f"  expira:     {payload['expira'] or 'perpetua'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
