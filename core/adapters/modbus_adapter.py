"""
core/adapters/modbus_adapter.py — Adaptador industrial Modbus TCP (ADR-0004).

Esqueleto con el MISMO contrato que MqttTelemetryAdapter: el cambio de
protocolo es transparente para agentes, servicios y UI.
  - Modo real:     AGENTDESK_MODBUS_HOST=host[:puerto] + pymodbus instalado
                   (lee holding registers y aplica `escala` por sensor).
  - Modo simulado: SimuladorPlanta determinista (sin PLC, sin red).

Los detalles del protocolo (registro, unit/slave, escala) viajan en la
metadata del MetricEvent — el contrato no se contamina (ADR-0001).
"""
from __future__ import annotations

import logging
import os

from core.adapters.base import BaseTelemetryAdapter

logger = logging.getLogger(__name__)

# Holding registers típicos de un PLC de línea (direcciones ilustrativas)
SENSORES: list[dict] = [
    # min_fisico/max_fisico: rango de validez FISICA ([INDUSTRIAL-INTEGRITY],
    # ADR-0021) — fuera de el, la lectura se descarta del Gemelo Digital.
    {
        "id": "temp_reactor_2", "nombre": "Temperatura Reactor 2",
        "registro": 40001, "unit": 1, "escala": 0.1, "unidad": "°C",
        "base": 180.0, "amplitud": 35.0,
        "umbral_warn": 205.0, "umbral_critico": 212.0,
        "min_fisico": 0.0, "max_fisico": 350.0,
    },
    {
        "id": "caudal_bomba_5", "nombre": "Caudal Bomba 5",
        "registro": 40003, "unit": 1, "escala": 0.01, "unidad": "m³/h",
        "base": 42.0, "amplitud": 12.0,
        "umbral_warn": 51.0, "umbral_critico": 53.5,
        "min_fisico": 0.0, "max_fisico": 120.0,
    },
]


# Tags ESCRIBIBLES ([INDUSTRIAL-ACTION], ADR-0024): min_escritura/max_escritura
# es el limite fisico de seguridad — ningun comando puede cruzarlo, lo valida
# el filtro determinista de base.py antes de tocar la red.
ACTUADORES: list[dict] = [
    {
        "id": "reset_alarma_e117", "nombre": "Reset Alarma E-117",
        "registro": 40100, "unit": 1, "escala": 1.0, "unidad": "",
        "min_escritura": 0.0, "max_escritura": 1.0,
    },
    {
        "id": "setpoint_temp_reactor_2", "nombre": "Setpoint Temperatura Reactor 2",
        "registro": 40010, "unit": 1, "escala": 0.1, "unidad": "°C",
        "min_escritura": 20.0, "max_escritura": 205.0,
    },
]


class ModbusTelemetryAdapter(BaseTelemetryAdapter):
    """TelemetryPort + ActuationPort sobre Modbus TCP; sin host usa SimuladorPlanta."""

    SENSORES = SENSORES
    ACTUADORES = ACTUADORES

    def __init__(self, host: str | None = None, intervalo_s: float = 5.0, **kw):
        super().__init__(intervalo_s=intervalo_s, **kw)
        self._host    = host if host is not None else os.environ.get("AGENTDESK_MODBUS_HOST", "")
        self._cliente = None   # pymodbus AsyncModbusTcpClient (lazy)
        # Base de direccionamiento confirmada por la primera lectura exitosa:
        # 40001 (convencion PDU estandar: registro 4xxxx -> offset 0-based) o
        # 1 (direccion literal 1-based, como define ModbusPal). None = aun
        # sin confirmar. La ESCRITURA nunca adivina: usa esta base o la
        # estandar, jamas prueba direcciones alternativas (ADR-0024).
        self._base_direccion: int | None = None

    def protocolo(self) -> str:
        return "modbus" if self._host else "simulador"

    def _leer_valor(self, sensor: dict) -> float:
        if not self._host:
            return self._simulador.leer(sensor)
        return self._leer_registro(sensor)

    @staticmethod
    def _kwargs_unidad(metodo, unit: int) -> dict:
        """pymodbus >=3.9 renombro slave= a device_id= — detecta por firma."""
        import inspect
        try:
            params = inspect.signature(metodo).parameters
        except (TypeError, ValueError):
            return {"device_id": unit}
        return {"device_id": unit} if "device_id" in params else {"slave": unit}

    def _leer_registro(self, sensor: dict) -> float:
        """
        Lectura real de un holding register (fase de conexión a PLC).
        Requiere pymodbus; si falta, degrada al simulador con aviso.
        """
        if self._cliente is None:
            try:
                from pymodbus.client import ModbusTcpClient
            except ImportError:
                logger.warning("pymodbus no instalado — sensor '%s' en modo simulador.", sensor["id"])
                return self._simulador.leer(sensor)
            host, _, puerto = self._host.partition(":")
            self._cliente = ModbusTcpClient(host, port=int(puerto or 502))
            if self._cliente.connect():
                logger.info("MODBUS: conexion establecida con %s:%s",
                            host, puerto or 502)
            else:
                logger.warning("MODBUS: no se pudo conectar a %s:%s — "
                               "verificar que el esclavo este escuchando",
                               host, puerto or 502)

        crudo = self._leer_crudo(sensor["registro"], sensor["unit"])
        return round(crudo * sensor["escala"], 2)

    def _leer_crudo(self, registro: int, unit: int) -> int:
        """
        Lee el valor crudo probando las 2 convenciones de direccionamiento:
        PDU estandar (4xxxx -> offset 0-based, base 40001) y direccion
        literal 1-based (como define ModbusPal, base 1). La primera lectura
        exitosa CONFIRMA la base para el resto de la sesion.
        """
        metodo = self._cliente.read_holding_registers
        kwargs = self._kwargs_unidad(metodo, unit)
        if self._base_direccion is not None:
            bases = [self._base_direccion]
        else:
            bases = [40001, 1]
        ultimo = None
        for base in bases:
            respuesta = metodo(registro - base, count=1, **kwargs)
            if not respuesta.isError():
                if self._base_direccion is None:
                    self._base_direccion = base
                    logger.info(
                        "MODBUS: convencion de direccionamiento confirmada "
                        "(base %d: registro %d -> offset %d)",
                        base, registro, registro - base,
                    )
                return respuesta.registers[0]
            ultimo = respuesta
        raise ConnectionError(f"Modbus error leyendo {registro}: {ultimo}")

    def _escribir_valor(self, actuador: dict, valor: float) -> str:
        """
        Escritura real de un holding register (Modbus Write, ADR-0024).
        Sin host o sin pymodbus: registro simulado (default de base.py).
        El comando YA paso el filtro determinista de escribir_tag().
        """
        if not self._host:
            return super()._escribir_valor(actuador, valor)
        try:
            from pymodbus.client import ModbusTcpClient  # noqa: F401
        except ImportError:
            logger.warning("pymodbus no instalado — escritura '%s' en modo simulador.",
                           actuador["id"])
            return super()._escribir_valor(actuador, valor)

        if self._cliente is None:
            from pymodbus.client import ModbusTcpClient
            host, _, puerto = self._host.partition(":")
            self._cliente = ModbusTcpClient(host, port=int(puerto or 502))
            self._cliente.connect()

        # La escritura NUNCA prueba direcciones alternativas (ADR-0024):
        # usa la base confirmada por lectura, o la estandar 40001.
        base   = self._base_direccion if self._base_direccion is not None else 40001
        offset = actuador["registro"] - base
        crudo  = int(round(valor / actuador["escala"]))
        metodo = self._cliente.write_register
        respuesta = metodo(offset, crudo,
                           **self._kwargs_unidad(metodo, actuador["unit"]))
        if respuesta.isError():
            raise ConnectionError(
                f"Modbus error escribiendo {actuador['registro']}: {respuesta}")
        return f"write_register({actuador['registro']}={crudo})"

    def leer_snapshot(self, bloques: list[dict]) -> dict:
        """
        Lectura puntual CONSOLIDADA para pipelines de análisis (Opción
        Paralelo): NO reemplaza el polling del ciclo (que sigue gobernado
        por SENSORES) — es una foto bajo demanda de los registros que cada
        agente de telemetría declara en su bloque `telemetria` de config.

        bloques: [{"unidad": <nombre>, "unit_id": <int>,
                   "registros": [{"registro", "variable", "escala", "unidad"}]}]
        Devuelve {unidad: {variable: {"valor", "unidad", "registro"}}};
        una unidad que falla queda como {unidad: {"error": <motivo>}} y las
        demás sobreviven — el snapshot jamás lanza.
        """
        snapshot: dict = {}
        for bloque in bloques:
            unidad = bloque.get("unidad", f"unit_{bloque.get('unit_id')}")
            lecturas: dict = {}
            try:
                for reg in bloque.get("registros", []):
                    sensor = {
                        "id":       f"{unidad}:{reg['variable']}",
                        "registro": reg["registro"],
                        "unit":     bloque.get("unit_id", 1),
                        "escala":   reg.get("escala", 1.0),
                        "unidad":   reg.get("unidad", ""),
                        # Defaults para el modo simulador (sin host/pymodbus)
                        "base":     reg.get("base", 50.0),
                        "amplitud": reg.get("amplitud", 10.0),
                    }
                    lecturas[reg["variable"]] = {
                        "valor":    float(self._leer_valor(sensor)),
                        "unidad":   sensor["unidad"],
                        "registro": sensor["registro"],
                    }
                snapshot[unidad] = lecturas
            except Exception as exc:
                logger.warning("MODBUS: snapshot de '%s' fallo (%s) — se continua "
                               "con el resto de unidades", unidad, exc)
                snapshot[unidad] = {"error": str(exc)}
        self._cerrar_cliente()
        return snapshot

    def _cerrar_cliente(self) -> None:
        """
        Cierra el socket TCP tras una lectura puntual (2026-07-20): cada
        corrida de la Opcion Paralelo instancia un ModbusTelemetryAdapter
        nuevo (main.py) — sin este cierre, el ModbusTcpClient quedaba
        abandonado a merced del recolector de basura, acumulando conexiones
        no cerradas limpiamente. Contra un simulador simple (single-thread,
        ej. ModbusPal) esa acumulacion termino dejandolo sin responder a
        NINGUNA peticion nueva ('No response received'), sin importar el
        cliente que la origine. leer_snapshot() es una foto puntual, no un
        polling persistente (ver docstring) — no hay razon para mantener
        el socket vivo entre llamadas.
        """
        if self._cliente is None:
            return
        try:
            self._cliente.close()
        except Exception:
            pass
        self._cliente = None
        self._base_direccion = None

    async def _reconectar(self) -> None:
        """Cierra el cliente Modbus roto para forzar una conexión nueva (ADR-0012)."""
        if self._cliente is not None:
            try:
                self._cliente.close()
            except Exception:
                pass
            self._cliente = None

    def detener(self) -> None:
        super().detener()
        if self._cliente is not None:
            try:
                self._cliente.close()
            except Exception:
                pass
            self._cliente = None
