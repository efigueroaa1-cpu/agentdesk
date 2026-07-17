# -*- coding: utf-8 -*-
"""
scripts/smoke_test_staging.py — Smoke Test de Integración Real (Fase 22, ADR-0020).

Verifica conectividad REAL (cero mocks) contra la infraestructura de staging
del piloto industrial:

  1. [SEC-DB]   Handshake de seguridad: las credenciales de AGENTDESK_DB_URL
                pasan la política Zero-Default (ADR-0016) — misma validación
                real que corre el Fail-Hard del arranque, no una copia.
  2. [PG]       Conexión real a PostgreSQL (asyncpg, SELECT 1) con timeout
                industrial acotado — y verificación de que el fallo, si
                ocurre, es RÁPIDO (fail-fast, no un cuelgue indefinido).
  3. [MQTT]     Conexión real al broker MQTT (paho, CONNACK) con el mismo
                contrato AGENTDESK_MQTT_BROKER=host[:puerto] del adaptador
                de planta (ADR-0004).
  4. [REDIS]    Ping real al broker de Queue Mode (AGENTDESK_QUEUE_URL) via
                la MISMA función `_broker_disponible()` que decide el modo
                distribuido en producción (ADR-0019).

Uso:
  python scripts/smoke_test_staging.py                  # chequea lo configurado, SKIP lo ausente
  python scripts/smoke_test_staging.py --todo-obligatorio   # staging CI: SKIP tambien es fallo

Códigos de salida: 0 = todo lo evaluado en verde; 1 = al menos un FAIL
(o un SKIP con --todo-obligatorio). Pensado para correr en el equipo del
cliente tras instalar, y en el pipeline de staging antes de cada release.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time

# Ejecutable tanto desde la raiz del repo como desde el bundle instalado
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TIMEOUT_PG_S    = 5.0    # mismo timeout que _verificar_conexion_async (ADR-0013)
TIMEOUT_MQTT_S  = 5.0
MARGEN_FAIL_FAST_S = 3.0  # un fallo debe reportarse en timeout+margen, no colgarse


def _resultado(nombre: str, estado: str, detalle: str, duracion_s: float) -> dict:
    return {"nombre": nombre, "estado": estado, "detalle": detalle,
            "duracion_s": round(duracion_s, 2)}


def chequear_credenciales_db() -> dict:
    """[SEC-DB] Zero-Default sobre AGENTDESK_DB_URL — reusa la validación real del arranque."""
    t0 = time.monotonic()
    db_url = os.environ.get("AGENTDESK_DB_URL", "").strip()
    if not db_url or db_url.startswith("sqlite"):
        return _resultado("SEC-DB", "SKIP",
                          "AGENTDESK_DB_URL ausente o sqlite (modo desktop valido)",
                          time.monotonic() - t0)
    from core.services.boot_diagnostics_service import _validar_db_url
    criticos = _validar_db_url()
    if criticos:
        return _resultado("SEC-DB", "FAIL", "; ".join(criticos), time.monotonic() - t0)
    return _resultado("SEC-DB", "PASS",
                      "credenciales de DB pasan la politica Zero-Default (ADR-0016)",
                      time.monotonic() - t0)


def chequear_postgres() -> dict:
    """[PG] Conexión real a PostgreSQL con timeout industrial y fail-fast verificado."""
    t0 = time.monotonic()
    db_url = os.environ.get("AGENTDESK_DB_URL", "").strip()
    if not db_url or db_url.startswith("sqlite"):
        return _resultado("PG", "SKIP",
                          "AGENTDESK_DB_URL ausente o sqlite — nada que verificar",
                          time.monotonic() - t0)
    try:
        import asyncpg
    except ImportError:
        return _resultado("PG", "FAIL",
                          "asyncpg NO empaquetado en este build — hidden import roto",
                          time.monotonic() - t0)

    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", db_url)

    async def _probar() -> str:
        conn = await asyncpg.connect(dsn, timeout=TIMEOUT_PG_S)
        try:
            fila = await conn.fetchval("SELECT 1")
            version = await conn.fetchval("SHOW server_version")
            assert fila == 1
            return str(version)
        finally:
            await conn.close()

    try:
        version = asyncio.run(asyncio.wait_for(_probar(), timeout=TIMEOUT_PG_S + 2))
        return _resultado("PG", "PASS",
                          f"SELECT 1 OK — PostgreSQL {version}", time.monotonic() - t0)
    except Exception as exc:
        transcurrido = time.monotonic() - t0
        detalle = f"{type(exc).__name__}: {exc}"
        # El timeout industrial TAMBIEN se verifica en el camino de fallo:
        # un servidor inalcanzable debe reportarse rapido, nunca colgar el
        # smoke test (ni el arranque real que usa el mismo timeout).
        if transcurrido > TIMEOUT_PG_S + MARGEN_FAIL_FAST_S:
            detalle += f" [ADEMAS: fallo LENTO ({transcurrido:.1f}s) — timeout no operando]"
        else:
            detalle += f" [fail-fast OK: {transcurrido:.1f}s <= {TIMEOUT_PG_S + MARGEN_FAIL_FAST_S:.0f}s]"
        return _resultado("PG", "FAIL", detalle, transcurrido)


def chequear_mqtt() -> dict:
    """[MQTT] CONNACK real contra el broker de planta (mismo contrato que el adaptador ADR-0004)."""
    t0 = time.monotonic()
    broker = os.environ.get("AGENTDESK_MQTT_BROKER", "").strip()
    if not broker:
        return _resultado("MQTT", "SKIP",
                          "AGENTDESK_MQTT_BROKER ausente — planta sin broker MQTT",
                          time.monotonic() - t0)
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        return _resultado("MQTT", "FAIL",
                          "paho-mqtt NO empaquetado en este build — hidden import roto",
                          time.monotonic() - t0)

    host, _, puerto = broker.partition(":")
    puerto = int(puerto) if puerto else 1883

    codigo_conexion: list = []

    def _on_connect(_cliente, _userdata, _flags, reason_code, _props=None):
        codigo_conexion.append(reason_code)

    try:
        cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id="agentdesk-smoke-test")
        cliente.on_connect = _on_connect
        usuario = os.environ.get("AGENTDESK_MQTT_USER", "")
        if usuario:
            cliente.username_pw_set(usuario, os.environ.get("AGENTDESK_MQTT_PASSWORD", ""))
        cliente.connect(host, puerto, keepalive=int(TIMEOUT_MQTT_S))
        cliente.loop_start()
        limite = time.monotonic() + TIMEOUT_MQTT_S
        while not codigo_conexion and time.monotonic() < limite:
            time.sleep(0.05)
        cliente.loop_stop()
        cliente.disconnect()
        if not codigo_conexion:
            raise TimeoutError(f"sin CONNACK en {TIMEOUT_MQTT_S:.0f}s")
        rc = codigo_conexion[0]
        if getattr(rc, "is_failure", False):
            raise ConnectionError(f"broker rechazo la conexion: {rc}")
        return _resultado("MQTT", "PASS",
                          f"CONNACK OK de {host}:{puerto} (rc={rc})", time.monotonic() - t0)
    except Exception as exc:
        transcurrido = time.monotonic() - t0
        detalle = f"{type(exc).__name__}: {exc}"
        if transcurrido > TIMEOUT_MQTT_S + MARGEN_FAIL_FAST_S:
            detalle += f" [ADEMAS: fallo LENTO ({transcurrido:.1f}s) — timeout no operando]"
        else:
            detalle += f" [fail-fast OK: {transcurrido:.1f}s]"
        return _resultado("MQTT", "FAIL", detalle, transcurrido)


def chequear_redis() -> dict:
    """[REDIS] Ping real via la MISMA función que decide el Queue Mode en producción."""
    t0 = time.monotonic()
    url = os.environ.get("AGENTDESK_QUEUE_URL", "").strip()
    if not url:
        return _resultado("REDIS", "SKIP",
                          "AGENTDESK_QUEUE_URL ausente — Queue Mode local (valido)",
                          time.monotonic() - t0)
    from core.services.queue_service import _broker_disponible
    if _broker_disponible(url):
        return _resultado("REDIS", "PASS", "PING real al broker OK — Queue Mode distribuido activable",
                          time.monotonic() - t0)
    return _resultado("REDIS", "FAIL",
                      "broker configurado pero el PING real fallo (ver log) — "
                      "el sistema degradaria a modo local", time.monotonic() - t0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test de staging (conexiones reales, sin mocks)")
    parser.add_argument("--todo-obligatorio", action="store_true",
                        help="Modo staging CI: un SKIP tambien es fallo (toda la infra debe estar)")
    args = parser.parse_args()

    print("=== AgentDesk Smoke Test de Staging (ADR-0020) — conexiones REALES, sin mocks ===")
    resultados = [
        chequear_credenciales_db(),
        chequear_postgres(),
        chequear_mqtt(),
        chequear_redis(),
    ]

    fallos = 0
    for r in resultados:
        marca = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[r["estado"]]
        print(f"  {marca} {r['nombre']:<7} ({r['duracion_s']:5.2f}s)  {r['detalle']}")
        if r["estado"] == "FAIL" or (r["estado"] == "SKIP" and args.todo_obligatorio):
            fallos += 1

    if fallos:
        print(f"=== SMOKE TEST FALLIDO: {fallos} chequeo(s) en rojo ===")
        return 1
    print("=== SMOKE TEST APROBADO ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
