"""
core/adapters/mqtt_adapter.py — Primer adaptador industrial (ADR-0004).

Puente entre señales de planta y el Puerto de Telemetría (ADR-0001):
  - Modo real:     broker MQTT vía paho-mqtt (AGENTDESK_MQTT_BROKER).
  - Modo simulado: SimuladorPlanta genera señales deterministas (seed fija)
    que cruzan umbrales — demo y tests sin broker, sin red, sin costo.

Cada lectura se normaliza a MetricEvent y se entrega a los suscriptores
(puente WebSocket hacia la UI, ReactorIndustrial hacia los agentes).
Instalación sin tocar core/api.py: main.py llama instalar_en_app(app, broadcast)
cuando AGENTDESK_INDUSTRIAL está definida.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import random
from typing import Awaitable, Callable

from core.ports.telemetry_port import MetricEvent
from core.timeutil import utcnow

logger = logging.getLogger(__name__)

# ── Catálogo de sensores (simulados o mapeados a topics MQTT) ──────────────────

SENSORES: list[dict] = [
    {
        "id": "temp_horno_1", "nombre": "Temperatura Horno 1",
        "topic": "planta/horno1/temperatura", "unidad": "°C",
        "base": 210.0, "amplitud": 40.0,
        "umbral_warn": 235.0, "umbral_critico": 245.0,
    },
    {
        "id": "presion_linea_a", "nombre": "Presión Línea A",
        "topic": "planta/lineaA/presion", "unidad": "bar",
        "base": 6.5, "amplitud": 1.8,
        "umbral_warn": 7.5, "umbral_critico": 8.0,
    },
    {
        "id": "vibracion_motor_3", "nombre": "Vibración Motor 3",
        "topic": "planta/motor3/vibracion", "unidad": "mm/s",
        "base": 2.8, "amplitud": 2.4,
        "umbral_warn": 4.3, "umbral_critico": 4.9,
    },
]


class SimuladorPlanta:
    """
    Fuente simulada determinista: onda senoidal + ruido con seed fija.
    El mismo tick produce siempre el mismo valor (asserts estables), y la
    amplitud está calibrada para cruzar umbrales warn/crítico periódicamente.
    """

    def __init__(self, seed: int = 42):
        self._rng  = random.Random(seed)  # nosec B311 - simulacion, no criptografia
        self._tick = 0

    def leer(self, sensor: dict) -> float:
        """Valor del sensor en el tick actual (avanza al llamar con avanzar())."""
        fase  = self._tick / 6.0
        onda  = math.sin(fase) * sensor["amplitud"]
        ruido = self._rng.uniform(-0.05, 0.05) * sensor["amplitud"]
        return round(sensor["base"] + onda + ruido, 2)

    def avanzar(self) -> None:
        self._tick += 1


def _nivel_de(sensor: dict, valor: float) -> str:
    if valor >= sensor["umbral_critico"]:
        return "critico"
    if valor >= sensor["umbral_warn"]:
        return "warn"
    return "info"


class ReactorIndustrial:
    """
    Reglas declarativas (condición sobre MetricEvent → acción async).
    La acción típica es disparar una tarea de agente vía
    orchestrator_service.ejecutar_tarea — reactividad sin polling.
    """

    def __init__(self):
        self._reglas: list[tuple[str, Callable[[MetricEvent], bool],
                                 Callable[[MetricEvent], Awaitable[None]]]] = []

    def registrar(self, descripcion: str,
                  condicion: Callable[[MetricEvent], bool],
                  accion: Callable[[MetricEvent], Awaitable[None]]) -> None:
        self._reglas.append((descripcion, condicion, accion))

    async def evaluar(self, evento: MetricEvent) -> list[str]:
        """Evalúa el evento contra todas las reglas; retorna las disparadas."""
        disparadas = []
        for descripcion, condicion, accion in self._reglas:
            try:
                if condicion(evento):
                    logger.info("REACTOR_INDUSTRIAL: regla disparada '%s' — fuente=%s valor=%s",
                                descripcion, evento.fuente, evento.valor)
                    await accion(evento)
                    disparadas.append(descripcion)
            except Exception as exc:
                logger.warning("REACTOR_INDUSTRIAL: regla '%s' fallo: %s", descripcion, exc)
        return disparadas


class MqttTelemetryAdapter:
    """
    Implementación de core.ports.telemetry_port.TelemetryPort para MQTT.
    Sin broker configurado usa SimuladorPlanta (mismo contrato, cero red).
    """

    def __init__(self, broker: str | None = None, intervalo_s: float = 5.0):
        self._broker      = broker or os.environ.get("AGENTDESK_MQTT_BROKER", "")
        self._intervalo_s = intervalo_s
        self._simulador   = SimuladorPlanta()
        self._estado      = {s["id"]: {"activo": True, "intervalo_min": 1,
                                       "ultima_fetch": None, "ultimo_valor": None}
                             for s in SENSORES}
        self._callbacks: list[Callable[[MetricEvent], Awaitable[None]]] = []
        self._task: asyncio.Task | None = None
        self.reactor = ReactorIndustrial()

    # ── Contrato TelemetryPort ────────────────────────────────────────────

    def fuentes(self) -> list[dict]:
        return [
            {
                "id":            s["id"],
                "nombre":        s["nombre"],
                "unidad":        s["unidad"],
                "protocolo":     "mqtt" if self._broker else "simulador",
                "topic":         s["topic"],
                "activo":        self._estado[s["id"]]["activo"],
                "intervalo_min": self._estado[s["id"]]["intervalo_min"],
                "ultima_fetch":  self._estado[s["id"]]["ultima_fetch"],
                "ultimo_valor":  self._estado[s["id"]]["ultimo_valor"],
            }
            for s in SENSORES
        ]

    def leer(self, fuente_id: int | str) -> list[MetricEvent]:
        """Lectura puntual de una fuente (bajo demanda)."""
        sensor = next((s for s in SENSORES if s["id"] == fuente_id), None)
        if sensor is None:
            return []
        return [self._evento_de(sensor, self._simulador.leer(sensor))]

    def suscribir(self, callback: Callable[[MetricEvent], Awaitable[None]]) -> None:
        self._callbacks.append(callback)

    def alternar(self, fuente_id: int | str, activo: bool) -> bool:
        if fuente_id not in self._estado:
            return False
        self._estado[fuente_id]["activo"] = bool(activo)
        return True

    def cambiar_frecuencia(self, fuente_id: int | str, intervalo_min: int) -> bool:
        if fuente_id not in self._estado or intervalo_min < 1:
            return False
        self._estado[fuente_id]["intervalo_min"] = int(intervalo_min)
        return True

    # ── Normalización y difusión ──────────────────────────────────────────

    def _evento_de(self, sensor: dict, valor: float) -> MetricEvent:
        nivel = _nivel_de(sensor, valor)
        return MetricEvent(
            fuente=sensor["id"],
            tipo="lectura_sensor",
            valor=valor,
            unidad=sensor["unidad"],
            ts=utcnow(),
            nivel=nivel,
            metadata={
                "nombre":         sensor["nombre"],
                "topic":          sensor["topic"],
                "protocolo":      "mqtt" if self._broker else "simulador",
                "umbral_warn":    sensor["umbral_warn"],
                "umbral_critico": sensor["umbral_critico"],
            },
        )

    async def _difundir(self, evento: MetricEvent) -> None:
        self._estado[evento.fuente]["ultima_fetch"] = evento.ts.isoformat() if evento.ts else None
        self._estado[evento.fuente]["ultimo_valor"] = evento.valor
        for cb in list(self._callbacks):
            try:
                await cb(evento)
            except Exception as exc:
                logger.warning("Telemetria industrial: suscriptor fallo: %s", exc)
        await self.reactor.evaluar(evento)

    # ── Ciclo de vida ─────────────────────────────────────────────────────

    async def ciclo(self, max_ticks: int | None = None) -> None:
        """Bucle de muestreo del simulador (o consumo MQTT si hay broker)."""
        if self._broker:
            await self._ciclo_mqtt()
            return
        tick = 0
        while max_ticks is None or tick < max_ticks:
            self._simulador.avanzar()
            for sensor in SENSORES:
                if not self._estado[sensor["id"]]["activo"]:
                    continue
                await self._difundir(self._evento_de(sensor, self._simulador.leer(sensor)))
            tick += 1
            if max_ticks is None or tick < max_ticks:
                await asyncio.sleep(self._intervalo_s)

    async def _ciclo_mqtt(self) -> None:
        """Suscripción a un broker MQTT real (requiere paho-mqtt instalado)."""
        try:
            import paho.mqtt.client as mqtt  # noqa: F401
        except ImportError:
            logger.warning("paho-mqtt no instalado — usando SimuladorPlanta como fallback.")
            self._broker = ""
            await self.ciclo()
            return

        import json as _json
        loop  = asyncio.get_running_loop()
        cola: asyncio.Queue = asyncio.Queue()

        def _on_message(_cliente, _userdata, msg):
            sensor = next((s for s in SENSORES if s["topic"] == msg.topic), None)
            if sensor is None:
                return
            try:
                valor = float(_json.loads(msg.payload).get("valor", msg.payload))
            except Exception:
                try:
                    valor = float(msg.payload)
                except Exception:
                    return
            loop.call_soon_threadsafe(cola.put_nowait, (sensor, valor))

        cliente = mqtt.Client()
        cliente.on_message = _on_message
        host, _, puerto = self._broker.partition(":")
        cliente.connect(host, int(puerto or 1883), keepalive=30)
        for s in SENSORES:
            cliente.subscribe(s["topic"])
        cliente.loop_start()
        logger.info("Adaptador MQTT conectado a %s (%d topics).", self._broker, len(SENSORES))
        try:
            while True:
                sensor, valor = await cola.get()
                if self._estado[sensor["id"]]["activo"]:
                    await self._difundir(self._evento_de(sensor, valor))
        finally:
            cliente.loop_stop()
            cliente.disconnect()

    def iniciar(self) -> asyncio.Task:
        """Arranca el ciclo como tarea de fondo (idempotente)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.ciclo())
        return self._task

    def detener(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()


# ── Composición (la invoca main.py, nunca core/api.py) ────────────────────────

def crear_puente_ws(broadcast: Callable[[dict], Awaitable[None]]):
    """Suscriptor que reenvía cada MetricEvent al WebSocket de la UI."""
    async def puente(evento: MetricEvent) -> None:
        data = evento.to_dict()
        # "tipo" del WS es el canal; el tipo del MetricEvent viaja aparte
        data["tipo_evento"] = data.pop("tipo")
        await broadcast({"tipo": "telemetria_industrial", **data})
    return puente


def instalar_en_app(app, broadcast: Callable[[dict], Awaitable[None]],
                    ejecutar_tarea: Callable[..., Awaitable[dict]] | None = None,
                    ) -> MqttTelemetryAdapter:
    """
    Registra el adaptador como handler de startup de la app FastAPI.
    `broadcast` y `ejecutar_tarea` llegan inyectados desde el composition
    root — este módulo no importa core.api ni core.services.
    """
    adaptador = MqttTelemetryAdapter()
    adaptador.suscribir(crear_puente_ws(broadcast))

    async def _alerta_critica(evento: MetricEvent) -> None:
        await broadcast({
            "tipo":    "alerta_industrial",
            "fuente":  evento.fuente,
            "nombre":  evento.metadata.get("nombre", evento.fuente),
            "valor":   evento.valor,
            "unidad":  evento.unidad,
            "nivel":   evento.nivel,
            "mensaje": f"Umbral crítico superado: {evento.metadata.get('nombre')} = "
                       f"{evento.valor} {evento.unidad}",
        })
        if ejecutar_tarea is not None:
            await ejecutar_tarea(evento)

    adaptador.reactor.registrar(
        "alerta por umbral critico",
        lambda e: e.nivel == "critico",
        _alerta_critica,
    )

    async def _arrancar():
        adaptador.iniciar()
        logger.info("Telemetria industrial activa (%s).",
                    "broker MQTT" if adaptador._broker else "SimuladorPlanta")

    app.add_event_handler("startup", _arrancar)
    app.add_event_handler("shutdown", adaptador.detener)
    return adaptador
