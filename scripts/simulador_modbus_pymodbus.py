"""
scripts/simulador_modbus_pymodbus.py — Planta Virtual de reemplazo (pymodbus).

Ante el bloqueo persistente de ModbusPal (puerto 5021 en LISTENING pero sin
respuesta a nivel de aplicacion Modbus, confirmado con dos reinicios
completos y con un cliente pymodbus aislado), este script levanta un
servidor Modbus TCP real con la misma libreria que usa el adaptador de
produccion (core.adapters.modbus_adapter.ModbusTelemetryAdapter) del lado
cliente -- asi la lectura que hagan los agentes es contra un servidor
Modbus TCP genuino, no un mock en memoria del propio proceso.

Mapa de esclavos (calca la telemetria real de config.json):
  U1, U2       -> holding register 40001 (temperatura) y 40002 (presion)
  U3, U4, U5   -> holding register 40001 (temperatura) unicamente

Direccionamiento: registro 40001 -> offset 0, 40002 -> offset 1 (convencion
PDU estandar; es la primera base que prueba ModbusTelemetryAdapter._leer_crudo).

Uso:  python scripts/simulador_modbus_pymodbus.py
Detener con Ctrl+C.
"""
import asyncio
import logging
import sys

from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PUERTO = 5021

# Valores fisicos reales (no vacios/cero) para que GroundingGuard [CRIT]
# no descarte las lecturas por campos sin cargar.
TEMPERATURA_C = 50
PRESION_BAR = 80

UNIDADES_CON_PRESION = (1, 2)
UNIDADES_SOLO_TEMPERATURA = (3, 4, 5)


def _bloque(valores: list[int]) -> ModbusSequentialDataBlock:
    # ModbusSequentialDataBlock indexa 1-based internamente (address - 1);
    # pasar 1 aqui deja el PDU offset 0 (equivalente a "40001") accesible.
    return ModbusSequentialDataBlock(1, valores)


def _construir_contexto() -> ModbusServerContext:
    dispositivos: dict[int, ModbusDeviceContext] = {}

    for unit_id in UNIDADES_CON_PRESION:
        dispositivos[unit_id] = ModbusDeviceContext(
            hr=_bloque([TEMPERATURA_C, PRESION_BAR]),
            ir=_bloque([TEMPERATURA_C, PRESION_BAR]),
            co=_bloque([0] * 8),
            di=_bloque([0] * 8),
        )

    for unit_id in UNIDADES_SOLO_TEMPERATURA:
        dispositivos[unit_id] = ModbusDeviceContext(
            hr=_bloque([TEMPERATURA_C]),
            ir=_bloque([TEMPERATURA_C]),
            co=_bloque([0] * 8),
            di=_bloque([0] * 8),
        )

    return ModbusServerContext(devices=dispositivos, single=False)


async def main() -> int:
    contexto = _construir_contexto()
    print(f"Simulador Modbus TCP (pymodbus) escuchando en {HOST}:{PUERTO}")
    print(f"Unidades activas: {sorted(dispositivos_ids())}")
    print("Ctrl+C para detener.")
    await StartAsyncTcpServer(context=contexto, address=(HOST, PUERTO))
    return 0


def dispositivos_ids() -> list[int]:
    return list(UNIDADES_CON_PRESION) + list(UNIDADES_SOLO_TEMPERATURA)


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nSimulador detenido.")
        sys.exit(0)
