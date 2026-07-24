"""
scripts/test_modbus_reading.py — Verificacion pre-lanzamiento de la Planta
Virtual (ModbusPal) usando el adaptador REAL de produccion
(core.adapters.modbus_adapter.ModbusTelemetryAdapter), no una lectura
manual reimplementada -- asi el resultado refleja exactamente lo que van
a leer los 5 agentes tecnicos U1-U5 en la Opcion 23.

Lee los bloques "telemetria" de cada agente_modbus_0X en config.json
(host/port/unit_id/registros) y hace un leer_snapshot() real.

Uso:  python scripts/test_modbus_reading.py
"""
import json
import sys

from core.path_manager import config_path
from core.adapters.modbus_adapter import ModbusTelemetryAdapter


def main() -> int:
    cfg = json.loads(config_path().read_text(encoding="utf-8"))

    bloques = []
    host_puerto = None
    for agente in cfg["agents"]:
        tel = agente.get("telemetria")
        if tel and tel.get("protocolo") == "modbus_tcp":
            bloques.append({
                "unidad":    agente["id"],
                "unit_id":   tel["unit_id"],
                "registros": tel["registros"],
            })
            if host_puerto is None:
                host_puerto = f"{tel['host']}:{tel['port']}"

    if not bloques:
        print("No hay bloques de telemetria modbus en config.json.")
        return 1

    print(f"Conectando a {host_puerto} ...")

    adaptador = ModbusTelemetryAdapter(host=host_puerto)
    snapshot = adaptador.leer_snapshot(bloques)

    print("\n=== Snapshot real leido de ModbusPal ===")
    todos_cero = True
    hubo_error = False
    for agente_id, valores in snapshot.items():
        print(f"\n{agente_id}:")
        if "error" in valores:
            hubo_error = True
            print(f"  ERROR: {valores['error']}")
            continue
        for variable, datos in valores.items():
            valor = datos.get("valor")
            unidad = datos.get("unidad", "")
            registro = datos.get("registro")
            print(f"  {variable} (registro {registro}): {valor} {unidad}")
            if valor not in (None, 0, 0.0):
                todos_cero = False

    print("\n=== Veredicto ===")
    if hubo_error:
        print("BLOQUEADO: al menos una unidad no respondio (ver errores arriba).")
        return 1
    if todos_cero:
        print("SOSPECHOSO: todos los valores son 0 -- puede ser el registro sin "
              "cargar en ModbusPal (real) o el simulador interno degradado "
              "(no confundir con datos reales).")
        return 1

    print("OK: valores numericos reales distintos de cero en las 5 unidades.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
