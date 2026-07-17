"""
core/adapters/base.py — Maquinaria común de los adaptadores industriales
(ADR-0004). Estado de fuentes, difusión con Cola Resiliente, ReactorIndustrial
y ciclo de muestreo. Cada protocolo (MQTT/Modbus/OPC-UA) solo define su
catálogo de sensores y cómo leer un valor.

Cola Resiliente (Queue Mode): en plantas con red inestable el WebSocket puede
caerse momentáneamente. Cada suscriptor tiene una cola pendiente acotada:
si la entrega falla (con reintentos + backoff), el evento se conserva y se
re-entrega EN ORDEN en cuanto el suscriptor vuelve — sin perder métricas y
sin crecer sin límite (se descarta lo más viejo al llenarse, dejando log).
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
from collections import deque
from typing import Awaitable, Callable

from core.ports.telemetry_port import MetricEvent
from core.timeutil import utcnow

logger = logging.getLogger(__name__)

Suscriptor = Callable[[MetricEvent], Awaitable[None]]


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
        fase  = self._tick / 6.0
        onda  = math.sin(fase) * sensor["amplitud"]
        ruido = self._rng.uniform(-0.05, 0.05) * sensor["amplitud"]
        return round(sensor["base"] + onda + ruido, 2)

    def avanzar(self) -> None:
        self._tick += 1


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


def _nivel_de(sensor: dict, valor: float) -> str:
    if valor >= sensor["umbral_critico"]:
        return "critico"
    if valor >= sensor["umbral_warn"]:
        return "warn"
    return "info"


class BaseTelemetryAdapter:
    """
    Implementación base de core.ports.telemetry_port.TelemetryPort.
    Subclases definen: SENSORES (catálogo), protocolo() y _leer_valor(sensor).
    """

    SENSORES: list[dict] = []

    def __init__(self, intervalo_s: float = 5.0,
                 max_cola: int = 500, max_reintentos: int = 3):
        self._intervalo_s    = intervalo_s
        self._max_reintentos = max_reintentos
        self._simulador      = SimuladorPlanta()
        self._estado = {s["id"]: {"activo": True, "intervalo_min": 1,
                                  "ultima_fetch": None, "ultimo_valor": None}
                        for s in self.SENSORES}
        self._callbacks: list[Suscriptor] = []
        # Cola Resiliente: pendientes POR suscriptor (uno caído no frena al resto)
        self._pendientes: dict[int, deque[MetricEvent]] = {}
        self._max_cola = max_cola
        self._task: asyncio.Task | None = None
        self.reactor = ReactorIndustrial()

    # ── A definir por cada protocolo ──────────────────────────────────────

    def protocolo(self) -> str:
        raise NotImplementedError

    def _leer_valor(self, sensor: dict) -> float:
        """Lee el valor actual del sensor (simulador o protocolo real)."""
        raise NotImplementedError

    # ── Contrato TelemetryPort ────────────────────────────────────────────

    def fuentes(self) -> list[dict]:
        return [
            {
                "id":            s["id"],
                "nombre":        s["nombre"],
                "unidad":        s["unidad"],
                "protocolo":     self.protocolo(),
                "activo":        self._estado[s["id"]]["activo"],
                "intervalo_min": self._estado[s["id"]]["intervalo_min"],
                "ultima_fetch":  self._estado[s["id"]]["ultima_fetch"],
                "ultimo_valor":  self._estado[s["id"]]["ultimo_valor"],
                **{k: s[k] for k in ("topic", "registro", "node_id") if k in s},
            }
            for s in self.SENSORES
        ]

    def leer(self, fuente_id: int | str) -> list[MetricEvent]:
        sensor = next((s for s in self.SENSORES if s["id"] == fuente_id), None)
        if sensor is None:
            return []
        return [self._evento_de(sensor, self._leer_valor(sensor))]

    def suscribir(self, callback: Suscriptor) -> None:
        self._callbacks.append(callback)
        self._pendientes[id(callback)] = deque(maxlen=self._max_cola)

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

    # ── Normalización y difusión resiliente ───────────────────────────────

    def _evento_de(self, sensor: dict, valor: float) -> MetricEvent:
        # Validacion de rango FISICO ([INDUSTRIAL-INTEGRITY], ADR-0021): una
        # lectura fuera de min_fisico/max_fisico es imposible en la magnitud
        # real (sensor roto o payload malicioso) — se marca envenenada, se
        # audita, y telemetry_history la excluye del Gemelo Digital. El
        # evento igual se difunde (el operador DEBE ver que algo anda mal),
        # pero como dato sospechoso, nunca como lectura legitima "critica".
        # Sensores sin rango declarado (dobles de prueba, adaptadores de
        # terceros) no validan: el guardian ya exige el rango en los
        # catalogos reales, y un KeyError aqui seria tratado por ciclo()
        # como caida de red -> bucle de reconexion infinito.
        min_fisico = sensor.get("min_fisico", float("-inf"))
        max_fisico = sensor.get("max_fisico", float("inf"))
        fuera_de_rango = not (min_fisico <= valor <= max_fisico)
        if fuera_de_rango:
            logger.warning(
                "AUDITORIA_SEGURIDAD: lectura fisicamente imposible en '%s' — "
                "valor=%s fuera de [%s, %s] %s (data poisoning o sensor roto); "
                "excluida del Gemelo Digital",
                sensor["id"], valor, min_fisico, max_fisico,
                sensor["unidad"],
            )
        return MetricEvent(
            fuente=sensor["id"],
            tipo="lectura_sensor",
            valor=valor,
            unidad=sensor["unidad"],
            ts=utcnow(),
            nivel="critico" if fuera_de_rango else _nivel_de(sensor, valor),
            metadata={
                "nombre":         sensor["nombre"],
                "protocolo":      self.protocolo(),
                "umbral_warn":    sensor["umbral_warn"],
                "umbral_critico": sensor["umbral_critico"],
                **({"fuera_de_rango_fisico": True} if fuera_de_rango else {}),
                **{k: sensor[k] for k in ("topic", "registro", "node_id") if k in sensor},
            },
        )

    async def _entregar(self, cb: Suscriptor, evento: MetricEvent) -> bool:
        """Un intento de entrega con reintentos + backoff exponencial corto."""
        for intento in range(self._max_reintentos):
            try:
                await cb(evento)
                return True
            except Exception as exc:
                if intento < self._max_reintentos - 1:
                    await asyncio.sleep(0.05 * (2 ** intento))
                else:
                    logger.warning("Telemetria: suscriptor sin responder (%s) — evento a cola", exc)
        return False

    async def _difundir(self, evento: MetricEvent) -> None:
        self._estado[evento.fuente]["ultima_fetch"] = evento.ts.isoformat() if evento.ts else None
        self._estado[evento.fuente]["ultimo_valor"] = evento.valor

        # Historial OT del Gemelo Digital (Fase 23, ADR-0021) — best-effort;
        # descarta internamente los eventos marcados fuera de rango fisico.
        try:
            from core.telemetry_history import registrar_evento
            registrar_evento(evento.to_dict())
        except Exception:
            pass

        for cb in list(self._callbacks):
            cola = self._pendientes.setdefault(id(cb), deque(maxlen=self._max_cola))

            # 1) Drenar pendientes EN ORDEN antes del evento nuevo
            while cola:
                if await self._entregar(cb, cola[0]):
                    cola.popleft()
                else:
                    break

            # 2) Evento actual: directo si la cola quedó vacía, si no a la cola
            if cola or not await self._entregar(cb, evento):
                if len(cola) == cola.maxlen:
                    logger.warning("Telemetria: cola llena (%d) — se descarta el evento mas antiguo",
                                   cola.maxlen)
                cola.append(evento)

        await self.reactor.evaluar(evento)

    def pendientes(self) -> int:
        """Total de eventos esperando re-entrega (diagnóstico Queue Mode)."""
        return sum(len(c) for c in self._pendientes.values())

    # ── Ciclo de vida ─────────────────────────────────────────────────────

    async def ciclo(self, max_ticks: int | None = None) -> None:
        """
        Bucle de muestreo por polling con reconexión automática (ADR-0012).

        Si _leer_valor() falla (PLC/broker caído, timeout de red), el ciclo
        NO muere: aplica backoff exponencial (2s, 4s, 8s... tope 60s), llama
        al hook _reconectar() de la subclase (cierra el cliente roto para
        forzar una conexión nueva) y reintenta. Un ciclo exitoso resetea el
        backoff a cero — la recuperación es tan rápida como la caída.
        """
        tick = 0
        backoff_s = 0.0
        while max_ticks is None or tick < max_ticks:
            self._simulador.avanzar()
            try:
                for sensor in self.SENSORES:
                    if not self._estado[sensor["id"]]["activo"]:
                        continue
                    await self._difundir(self._evento_de(sensor, self._leer_valor(sensor)))
                backoff_s = 0.0
            except Exception as exc:
                backoff_s = 2.0 if backoff_s == 0.0 else min(backoff_s * 2, 60.0)
                logger.warning(
                    "Telemetria (%s): fallo de lectura/conexion (%s) — reconectando en %.0fs",
                    self.protocolo(), exc, backoff_s,
                )
                await self._reconectar()
                await asyncio.sleep(backoff_s)
                continue
            tick += 1
            if max_ticks is None or tick < max_ticks:
                await asyncio.sleep(self._intervalo_s)

    async def _reconectar(self) -> None:
        """
        Hook de reconexión (ADR-0012): cada adaptador que mantenga un
        cliente con estado (Modbus, OPC-UA) lo sobreescribe para cerrar y
        anular ese cliente, forzando una conexión nueva en el próximo
        intento de lectura. No-op por defecto (p.ej. SimuladorPlanta puro).
        """
        return None

    def iniciar(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.ciclo())
        return self._task

    def detener(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
