"""
core/adapters/mqtt_adapter.py — Adaptador industrial MQTT (ADR-0004).

Puente entre señales de planta y el Puerto de Telemetría (ADR-0001):
  - Modo real:     broker MQTT vía paho-mqtt (AGENTDESK_MQTT_BROKER=host[:puerto]).
  - Modo simulado: SimuladorPlanta determinista (sin broker, sin red, sin costo).

El cambio simulador⇄broker es SOLO por variable de entorno: el contrato
MetricEvent y el flujo hacia el Dashboard no cambian. La maquinaria común
(estado, Cola Resiliente, ReactorIndustrial, ciclo) vive en base.py.
Instalación sin tocar core/api.py: main.py llama instalar_en_app(app, broadcast).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable

from core.adapters.base import (  # noqa: F401  (re-export para compatibilidad)
    BaseTelemetryAdapter,
    ReactorIndustrial,
    SimuladorPlanta,
)
from core.ports.telemetry_port import MetricEvent

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


class MqttTelemetryAdapter(BaseTelemetryAdapter):
    """TelemetryPort sobre MQTT; sin broker configurado usa SimuladorPlanta."""

    SENSORES = SENSORES

    def __init__(self, broker: str | None = None, intervalo_s: float = 5.0, **kw):
        super().__init__(intervalo_s=intervalo_s, **kw)
        self._broker = broker if broker is not None else os.environ.get("AGENTDESK_MQTT_BROKER", "")

    def protocolo(self) -> str:
        return "mqtt" if self._broker else "simulador"

    def _leer_valor(self, sensor: dict) -> float:
        # En modo broker las lecturas llegan por _ciclo_mqtt; el polling del
        # simulador cubre el modo demo y las lecturas puntuales leer().
        return self._simulador.leer(sensor)

    # ── Modo broker real ──────────────────────────────────────────────────

    async def ciclo(self, max_ticks: int | None = None) -> None:
        if self._broker and max_ticks is None:
            await self._ciclo_mqtt()
            return
        await super().ciclo(max_ticks=max_ticks)

    async def _ciclo_mqtt(self) -> None:
        """Suscripción a un broker MQTT real (requiere paho-mqtt instalado)."""
        try:
            import paho.mqtt.client as mqtt  # noqa: F401
        except ImportError:
            logger.warning("paho-mqtt no instalado — usando SimuladorPlanta como fallback.")
            self._broker = ""
            await super().ciclo()
            return

        import json as _json
        loop = asyncio.get_running_loop()
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
        logger.info("Telemetria industrial activa (%s).", adaptador.protocolo())

    app.add_event_handler("startup", _arrancar)
    app.add_event_handler("shutdown", adaptador.detener)
    return adaptador
