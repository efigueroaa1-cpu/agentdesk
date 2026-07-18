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
    # min_fisico/max_fisico (ADR-0021, [INDUSTRIAL-INTEGRITY]): rango de
    # validez FISICA de la magnitud, no de alarma de proceso — una lectura
    # fuera de este rango es imposible (sensor roto, payload malicioso) y
    # se descarta del Gemelo Digital en vez de tratarse como "muy critica".
    {
        "id": "temp_horno_1", "nombre": "Temperatura Horno 1",
        "topic": "planta/horno1/temperatura", "unidad": "°C",
        "base": 210.0, "amplitud": 40.0,
        "umbral_warn": 235.0, "umbral_critico": 245.0,
        "min_fisico": 0.0, "max_fisico": 400.0,
    },
    {
        "id": "presion_linea_a", "nombre": "Presión Línea A",
        "topic": "planta/lineaA/presion", "unidad": "bar",
        "base": 6.5, "amplitud": 1.8,
        "umbral_warn": 7.5, "umbral_critico": 8.0,
        "min_fisico": 0.0, "max_fisico": 20.0,
    },
    {
        "id": "vibracion_motor_3", "nombre": "Vibración Motor 3",
        "topic": "planta/motor3/vibracion", "unidad": "mm/s",
        "base": 2.8, "amplitud": 2.4,
        "umbral_warn": 4.3, "umbral_critico": 4.9,
        "min_fisico": 0.0, "max_fisico": 50.0,
    },
]


# Tags ESCRIBIBLES ([INDUSTRIAL-ACTION], ADR-0024): topics de comando con
# limite fisico de seguridad validado por el filtro determinista de base.py.
ACTUADORES: list[dict] = [
    {
        "id": "setpoint_horno_1", "nombre": "Setpoint Horno 1",
        "topic": "planta/horno1/cmd/setpoint", "unidad": "°C",
        "min_escritura": 20.0, "max_escritura": 235.0,
    },
    {
        "id": "reset_alarma_linea_a", "nombre": "Reset Alarma Linea A",
        "topic": "planta/lineaA/cmd/reset_alarma", "unidad": "",
        "min_escritura": 0.0, "max_escritura": 1.0,
    },
]


class MqttTelemetryAdapter(BaseTelemetryAdapter):
    """TelemetryPort + ActuationPort sobre MQTT; sin broker usa SimuladorPlanta."""

    SENSORES = SENSORES
    ACTUADORES = ACTUADORES

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

    def _escribir_valor(self, actuador: dict, valor: float) -> str:
        """
        Publicacion real de comando (MQTT Publish, ADR-0024). Sin broker o
        sin paho-mqtt: registro simulado (default de base.py). El comando
        YA paso el filtro determinista de escribir_tag().
        """
        if not self._broker:
            return super()._escribir_valor(actuador, valor)
        try:
            import paho.mqtt.publish as publish
        except ImportError:
            logger.warning("paho-mqtt no instalado — comando '%s' en modo simulador.",
                           actuador["id"])
            return super()._escribir_valor(actuador, valor)

        import json as _json
        host, _, puerto = self._broker.partition(":")
        publish.single(
            actuador["topic"],
            payload=_json.dumps({"valor": valor}),
            hostname=host, port=int(puerto or 1883), qos=1,
        )
        return f"publish({actuador['topic']})"

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

        # Conexion inicial con backoff exponencial (ADR-0012): connect() es
        # sincrono y lanza de inmediato si el broker esta caido — el
        # reintento automatico de paho-mqtt (loop_start) solo actua DESPUES
        # de una primera conexion exitosa, no antes.
        backoff_s = 2.0
        while True:
            try:
                cliente.connect(host, int(puerto or 1883), keepalive=30)
                break
            except Exception as exc:
                logger.warning(
                    "Adaptador MQTT: fallo al conectar a %s (%s) — reintento en %.0fs",
                    self._broker, exc, backoff_s,
                )
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, 60.0)

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
