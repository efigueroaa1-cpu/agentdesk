# -*- coding: utf-8 -*-
"""
tests/industrial/test_ot_reconexion.py — Resiliencia de Mensajería OT (Fase 14, ADR-0012).

Criterio de éxito: el sistema lee un registro Modbus simulado y, ante una
caída de red (simulada), reconecta automáticamente con backoff exponencial
(2s, 4s, 8s...) y retransmite la telemetría sin pérdida de datos apenas se
recupera — tanto del lado de la FUENTE (PLC/broker caído) como del lado del
SUSCRIPTOR (WS caído, ya cubierto por la Cola Resiliente de la Fase 6).

pymodbus no está instalado en este entorno de desarrollo (dependencia
opcional, ADR-0005/0007) — se inyecta un doble de prueba en sys.modules
para simular un PLC real que falla y se recupera, sin depender del paquete
real ni de un PLC físico.
"""
import asyncio
import sys
import types
import unittest
from unittest.mock import patch

from core.adapters.base import BaseTelemetryAdapter
from core.adapters.modbus_adapter import SENSORES as _SENSORES_MODBUS, ModbusTelemetryAdapter


class _ModbusUnSoloRegistro(ModbusTelemetryAdapter):
    """
    Mismo adaptador Modbus real, acotado a UN solo registro — aísla el
    timing de la prueba del hecho de que el catálogo real tiene 2 sensores
    compartiendo la misma Cola Resiliente por suscriptor.
    """
    SENSORES = [dict(_SENSORES_MODBUS[0])]   # temp_reactor_2


class _AdaptadorPatronFallos(BaseTelemetryAdapter):
    """Doble de prueba genérico: falla/tiene éxito según un patrón fijo."""

    SENSORES = [{
        "id": "s1", "nombre": "Sensor 1", "unidad": "u",
        "base": 10.0, "amplitud": 1.0, "umbral_warn": 100.0, "umbral_critico": 200.0,
    }]

    def __init__(self, patron_fallos: list[bool], **kw):
        super().__init__(**kw)
        self._patron = list(patron_fallos)
        self.reconexiones = 0

    def protocolo(self) -> str:
        return "test"

    def _leer_valor(self, sensor):
        fallar = self._patron.pop(0) if self._patron else False
        if fallar:
            raise ConnectionError("caida de red simulada")
        return 42.0

    async def _reconectar(self) -> None:
        self.reconexiones += 1


class TestReconexionGenericaConBackoff(unittest.IsolatedAsyncioTestCase):
    """Prueba el mecanismo genérico en base.py, agnóstico al protocolo."""

    @patch("core.adapters.base.asyncio.sleep", return_value=None)
    async def test_01_ciclo_sobrevive_y_reconecta_tras_fallos(self, _mock_sleep):
        adaptador = _AdaptadorPatronFallos([True, True, False, False], intervalo_s=0.01)
        eventos = []

        async def _cb(evento):
            eventos.append(evento)
        adaptador.suscribir(_cb)

        await adaptador.ciclo(max_ticks=2)

        self.assertEqual(adaptador.reconexiones, 2, "Debe reconectar una vez por fallo")
        self.assertEqual(len(eventos), 2, "Los 2 ticks exitosos deben entregarse sin perdida")
        self.assertTrue(all(e.valor == 42.0 for e in eventos))

    @patch("core.adapters.base.asyncio.sleep", return_value=None)
    async def test_02_backoff_exponencial_2_4_8(self, mock_sleep):
        adaptador = _AdaptadorPatronFallos([True, True, True, False], intervalo_s=0.01)
        await adaptador.ciclo(max_ticks=1)

        llamadas = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertEqual(llamadas[:3], [2.0, 4.0, 8.0],
                          "El backoff debe escalar 2s, 4s, 8s ante fallos consecutivos")

    @patch("core.adapters.base.asyncio.sleep", return_value=None)
    async def test_03_backoff_resetea_tras_una_recuperacion_exitosa(self, mock_sleep):
        """Falla, se recupera, vuelve a fallar -> el backoff arranca de nuevo en 2s."""
        adaptador = _AdaptadorPatronFallos([True, False, True, False], intervalo_s=0.01)
        await adaptador.ciclo(max_ticks=2)

        llamadas = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertEqual(llamadas[0], 2.0)                    # primer fallo
        self.assertIn(0.01, llamadas)                         # intervalo normal tras exito
        self.assertEqual(llamadas[-1], 2.0,
                          "Tras el tick exitoso, el SEGUNDO fallo debe volver a arrancar en 2s")


def _instalar_pymodbus_falso(fallos_antes_de_ok: int) -> dict:
    """
    Inyecta un doble de pymodbus en sys.modules: las primeras
    `fallos_antes_de_ok` lecturas lanzan ConnectionError (PLC caido), luego
    responde con un valor fijo. Cada reconexión crea un cliente NUEVO —
    contar las instancias prueba que _reconectar() de verdad fuerza una
    conexión nueva, no reintenta sobre el cliente roto.
    """
    contadores = {"conexiones": 0, "lecturas": 0}

    class _RespuestaFalsa:
        def __init__(self, valor):
            self.registers = [valor]
        def isError(self):
            return False

    class _ClienteFalso:
        def __init__(self, host, port=502):
            contadores["conexiones"] += 1
        def connect(self):
            return True
        def read_holding_registers(self, offset, count=1, slave=1):
            contadores["lecturas"] += 1
            if contadores["lecturas"] <= fallos_antes_de_ok:
                raise ConnectionError("PLC no responde (caida de red simulada)")
            return _RespuestaFalsa(1800)   # * escala 0.1 -> 180.0
        def close(self):
            pass

    mod_pymodbus = types.ModuleType("pymodbus")
    mod_client   = types.ModuleType("pymodbus.client")
    mod_client.ModbusTcpClient = _ClienteFalso
    sys.modules["pymodbus"]        = mod_pymodbus
    sys.modules["pymodbus.client"] = mod_client
    return contadores


class TestReconexionModbusSimulada(unittest.IsolatedAsyncioTestCase):
    """Criterio de éxito completo: registro Modbus simulado + caída + reconexión."""

    def tearDown(self):
        sys.modules.pop("pymodbus.client", None)
        sys.modules.pop("pymodbus", None)

    @patch("core.adapters.base.asyncio.sleep", return_value=None)
    async def test_04_lee_registro_modbus_y_reconecta_sin_perder_datos(self, _mock_sleep):
        contadores = _instalar_pymodbus_falso(fallos_antes_de_ok=2)

        adaptador = _ModbusUnSoloRegistro(host="10.0.0.7:502", intervalo_s=0.01)
        self.assertEqual(adaptador.protocolo(), "modbus")

        eventos = []
        async def _cb(evento):
            eventos.append(evento)
        adaptador.suscribir(_cb)

        await adaptador.ciclo(max_ticks=1)

        self.assertTrue(eventos, "El registro debe leerse y entregarse tras reconectar")
        self.assertAlmostEqual(eventos[-1].valor, 180.0, places=1)
        self.assertGreaterEqual(contadores["conexiones"], 2,
                                 "_reconectar() debe forzar un cliente NUEVO, no reusar el roto")

    @patch("core.adapters.base.asyncio.sleep", return_value=None)
    async def test_05_recuperacion_de_fuente_mas_cola_de_suscriptor_sin_perdida(self, _mock_sleep):
        """
        Combina ambos lados de la resiliencia: la FUENTE (PLC) se cae y
        reconecta (Fase 14, nuevo), y el SUSCRIPTOR (WS) agota sus
        reintentos y cae a la Cola Resiliente (Fase 6, ya existente) — que
        lo re-entrega en el siguiente ciclo. Cero eventos perdidos en
        ninguno de los dos lados.
        """
        _instalar_pymodbus_falso(fallos_antes_de_ok=1)
        adaptador = _ModbusUnSoloRegistro(host="10.0.0.7:502", intervalo_s=0.01)

        llamadas_suscriptor = {"n": 0}
        entregados = []

        async def _suscriptor_inestable(evento):
            llamadas_suscriptor["n"] += 1
            if llamadas_suscriptor["n"] <= 3:   # agota los 3 reintentos de _entregar()
                raise TimeoutError("WS momentaneamente caido")
            entregados.append(evento)

        adaptador.suscribir(_suscriptor_inestable)

        await adaptador.ciclo(max_ticks=1)   # fuente reconecta; suscriptor agota reintentos -> a la cola
        self.assertGreater(adaptador.pendientes(), 0,
                            "El evento debe quedar en la Cola Resiliente tras agotar los reintentos")

        await adaptador.ciclo(max_ticks=1)   # siguiente ciclo: drena la cola + entrega lo nuevo
        self.assertEqual(adaptador.pendientes(), 0, "La cola debe drenarse por completo, nada varado")
        self.assertTrue(entregados, "El evento debe llegar pese a la falla de fuente Y de suscriptor")
        self.assertAlmostEqual(entregados[-1].valor, 180.0, places=1)


if __name__ == "__main__":
    unittest.main()
