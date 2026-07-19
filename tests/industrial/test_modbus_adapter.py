# -*- coding: utf-8 -*-
"""
tests/industrial/test_modbus_adapter.py — Contrato del adaptador Modbus (Fase 6).
Mismo contrato que MQTT: el cambio de protocolo es transparente.
"""
import asyncio
import unittest

from core.adapters.modbus_adapter import SENSORES, ModbusTelemetryAdapter
from core.ports.telemetry_port import MetricEvent, TelemetryPort


class TestModbusAdapter(unittest.TestCase):

    def test_01_contrato_telemetry_port(self):
        self.assertIsInstance(ModbusTelemetryAdapter(), TelemetryPort)

    def test_02_protocolo_conmuta_por_configuracion(self):
        self.assertEqual(ModbusTelemetryAdapter(host="").protocolo(), "simulador")
        self.assertEqual(ModbusTelemetryAdapter(host="10.0.0.7:502").protocolo(), "modbus")

    def test_03_metadata_transporta_el_registro(self):
        """El detalle Modbus (registro/holding) viaja en metadata, no en el contrato."""
        evento = ModbusTelemetryAdapter(host="").leer("temp_reactor_2")[0]
        self.assertIsInstance(evento, MetricEvent)
        self.assertEqual(evento.metadata["registro"], 40001)
        self.assertEqual(evento.unidad, "°C")

    def test_04_ciclo_simulado_emite_todos_los_sensores(self):
        recibidos: list[MetricEvent] = []

        async def escenario():
            adaptador = ModbusTelemetryAdapter(host="", intervalo_s=0)

            async def captura(e: MetricEvent) -> None:
                recibidos.append(e)

            adaptador.suscribir(captura)
            await adaptador.ciclo(max_ticks=3)

        asyncio.run(escenario())
        self.assertEqual(len(recibidos), 3 * len(SENSORES))
        self.assertEqual({e.fuente for e in recibidos}, {s["id"] for s in SENSORES})


class TestLeerSnapshot(unittest.TestCase):
    """leer_snapshot: lectura puntual consolidada para pipelines de análisis
    (Opción Paralelo) — sin host degrada al simulador, jamás lanza."""

    BLOQUES = [
        {"unidad": "Agente Telemetria Modbus U1", "unit_id": 1,
         "registros": [
             {"registro": 40001, "variable": "temperatura", "escala": 0.1, "unidad": "C"},
             {"registro": 40002, "variable": "presion", "tipo": "holding_register",
              "escala": 0.01, "unidad": "bar"},
         ]},
        {"unidad": "Agente Telemetria Modbus U3", "unit_id": 3,
         "registros": [
             {"registro": 40001, "variable": "temperatura", "escala": 0.1, "unidad": "C"},
         ]},
    ]

    def test_05_snapshot_simulado_estructura_completa(self):
        snap = ModbusTelemetryAdapter(host="").leer_snapshot(self.BLOQUES)
        self.assertEqual(set(snap), {"Agente Telemetria Modbus U1",
                                     "Agente Telemetria Modbus U3"})
        u1 = snap["Agente Telemetria Modbus U1"]
        self.assertEqual(set(u1), {"temperatura", "presion"})
        for variable, lectura in u1.items():
            self.assertIsInstance(lectura["valor"], float)
            self.assertIn("unidad", lectura)
            self.assertIn("registro", lectura)

    def test_06_snapshot_vacio_sin_bloques(self):
        self.assertEqual(ModbusTelemetryAdapter(host="").leer_snapshot([]), {})

    def test_07_error_en_una_unidad_no_rompe_el_snapshot(self):
        """Una unidad que falla se reporta como error y las demás sobreviven."""
        adaptador = ModbusTelemetryAdapter(host="")

        def _explota(sensor):
            if sensor.get("unit") == 3:
                raise ConnectionError("unidad 3 caida")
            return 42.0

        adaptador._leer_valor = _explota
        snap = adaptador.leer_snapshot(self.BLOQUES)
        u1 = snap["Agente Telemetria Modbus U1"]
        self.assertEqual(u1["temperatura"]["valor"], 42.0)
        self.assertIn("error", snap["Agente Telemetria Modbus U3"])


class _RespuestaFake:
    def __init__(self, registers=None, error=False):
        self.registers = registers or []
        self._error = error

    def isError(self):
        return self._error


class _ClienteFakeModbusPal:
    """Simula ModbusPal: registros definidos en la direccion LITERAL 40001
    (offset 40000) — la convencion PDU estandar (offset 0) da error. API
    pymodbus >= 3.9 (device_id, sin slave)."""

    def __init__(self):
        self.lecturas = []      # (offset, kwargs)
        self.escrituras = []    # (offset, valor, kwargs)

    def read_holding_registers(self, address, count=1, device_id=None):
        self.lecturas.append((address, {"device_id": device_id}))
        if address == 40000:
            return _RespuestaFake(registers=[20])
        return _RespuestaFake(error=True)

    def write_register(self, address, value, device_id=None):
        self.escrituras.append((address, value, {"device_id": device_id}))
        return _RespuestaFake()


class _ClienteFakeLegado:
    """API pymodbus < 3.9: acepta slave=, convencion PDU estandar (offset 0)."""

    def __init__(self):
        self.lecturas = []

    def read_holding_registers(self, address, count=1, slave=None):
        self.lecturas.append((address, {"slave": slave}))
        if address == 0:
            return _RespuestaFake(registers=[215])
        return _RespuestaFake(error=True)


class TestCompatibilidadPymodbus(unittest.TestCase):
    """Firma device_id/slave + doble convencion de direccionamiento."""

    SENSOR = {"id": "u1:temperatura", "registro": 40001, "unit": 1,
              "escala": 1.0, "unidad": "C", "base": 50.0, "amplitud": 10.0}

    def _adaptador(self, cliente):
        a = ModbusTelemetryAdapter(host="127.0.0.1:5021")
        a._cliente = cliente   # evita crear cliente real (y el import pymodbus)
        return a

    def test_08_direccion_literal_modbuspal_y_device_id(self):
        """Offset estandar falla -> cae a direccion literal; usa device_id."""
        cliente = _ClienteFakeModbusPal()
        a = self._adaptador(cliente)
        valor = a._leer_registro(self.SENSOR)
        self.assertEqual(valor, 20.0, "crudo 20 con escala 1.0 = 20.0 (Verdad Tecnica)")
        self.assertEqual([l[0] for l in cliente.lecturas], [0, 40000],
                         "debe probar offset estandar y caer al literal")
        self.assertEqual(cliente.lecturas[0][1], {"device_id": 1})

    def test_09_convencion_confirmada_no_se_reprueba(self):
        """Tras confirmar la convencion, la 2da lectura va directo (1 llamada)."""
        cliente = _ClienteFakeModbusPal()
        a = self._adaptador(cliente)
        a._leer_registro(self.SENSOR)
        llamadas_previas = len(cliente.lecturas)
        a._leer_registro(self.SENSOR)
        self.assertEqual(len(cliente.lecturas), llamadas_previas + 1)
        self.assertEqual(cliente.lecturas[-1][0], 40000)

    def test_10_api_legada_slave_y_offset_estandar(self):
        cliente = _ClienteFakeLegado()
        a = self._adaptador(cliente)
        sensor = dict(self.SENSOR, escala=0.1)
        self.assertEqual(a._leer_registro(sensor), 21.5)
        self.assertEqual(cliente.lecturas[0], (0, {"slave": 1}))

    def test_11_escritura_usa_convencion_confirmada_sin_fallback(self):
        """La ESCRITURA jamas adivina direcciones: usa la convencion confirmada
        por lectura (o la estandar); un error de direccion lanza, no reintenta."""
        cliente = _ClienteFakeModbusPal()
        a = self._adaptador(cliente)
        a._leer_registro(self.SENSOR)          # confirma convencion literal
        actuador = {"id": "setpoint", "registro": 40010, "unit": 1,
                    "escala": 1.0, "unidad": "C",
                    "min_escritura": 0.0, "max_escritura": 100.0}
        a._escribir_valor(actuador, 25.0)
        self.assertEqual(len(cliente.escrituras), 1)
        self.assertEqual(cliente.escrituras[0][0], 40009,
                         "misma convencion literal confirmada en lectura")
        self.assertEqual(cliente.escrituras[0][1], 25)


if __name__ == "__main__":
    unittest.main()
