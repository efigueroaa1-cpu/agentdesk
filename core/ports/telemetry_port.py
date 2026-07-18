"""
core/ports/telemetry_port.py — Puerto de Telemetría agnóstico (ADR-0001).

Contrato único para toda fuente de telemetría: hoy los adaptadores son web
(REST + WebSocket del monitor); mañana pueden ser OT industriales
(Modbus TCP, OPC-UA) implementando este mismo Protocol sin tocar el núcleo
ni la UI. Es el espejo backend del puerto frontend useMonitorData.js.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Protocol, runtime_checkable


@dataclass(frozen=True)
class MetricEvent:
    """
    Evento de telemetría normalizado, independiente del protocolo de origen.

    `fuente` identifica el emisor (URL monitoreada, nodo Modbus, tag OPC-UA);
    `tipo` clasifica el evento (lectura, alerta, estado); `valor`/`unidad`
    portan la medición; `metadata` lleva lo específico del protocolo sin
    contaminar el contrato (p.ej. registro Modbus, nodeId OPC-UA).
    """
    fuente:    str
    tipo:      str
    valor:     float | str | None = None
    unidad:    str = ""
    ts:        datetime | None = None
    nivel:     str = "info"                      # info | warn | critico
    metadata:  dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fuente":   self.fuente,
            "tipo":     self.tipo,
            "valor":    self.valor,
            "unidad":   self.unidad,
            "ts":       self.ts.isoformat() if self.ts else None,
            "nivel":    self.nivel,
            "metadata": self.metadata,
        }


@runtime_checkable
class TelemetryPort(Protocol):
    """
    Interfaz que debe implementar todo adaptador de telemetría.

    Adaptador actual: web_monitor (scraping/APIs REST + broadcast WS).
    Adaptadores futuros: ModbusAdapter, OpcUaAdapter — solo implementan
    estos métodos; núcleo, scheduler y frontend no cambian.
    """

    def fuentes(self) -> list[dict]:
        """Fuentes registradas con su estado (id, nombre, activo, intervalo)."""
        ...

    def leer(self, fuente_id: int | str) -> list[MetricEvent]:
        """Lectura puntual (bajo demanda) de una fuente."""
        ...

    def suscribir(self, callback: Callable[[MetricEvent], None]) -> None:
        """Registra un callback para recibir eventos en tiempo real."""
        ...

    def alternar(self, fuente_id: int | str, activo: bool) -> bool:
        """Activa/pausa la recolección de una fuente."""
        ...

    def cambiar_frecuencia(self, fuente_id: int | str, intervalo_min: int) -> bool:
        """Ajusta el intervalo de muestreo de una fuente."""
        ...


@runtime_checkable
class ActuationPort(Protocol):
    """
    Puerto de ACTUACION (Fase 26, ADR-0024): escritura hacia la planta
    (Modbus write, MQTT publish). Protocolo SEPARADO de TelemetryPort a
    proposito — leer es inocuo, escribir puede mover fierros: un adaptador
    solo-lectura no debe verse obligado a implementar escritura, y el
    codigo que actua debe declararlo pidiendo ESTE puerto.

    Contrato de seguridad (obligatorio para toda implementacion):
      - `actuadores()` expone el catalogo con limites fisicos de escritura
        (min_escritura/max_escritura) por tag.
      - `escribir_tag()` DEBE pasar el comando por el filtro determinista
        de limites ANTES de tocar la red, y rechazar con auditoria todo
        valor fuera de rango. Nunca decide un LLM: solo valida aritmetica.
      - La aprobacion humana (Human-in-the-loop) NO vive aqui: es previa,
        en ot_command_service — este puerto asume comandos YA aprobados.
    """

    def actuadores(self) -> list[dict]:
        """Catalogo de tags escribibles con sus limites de seguridad."""
        ...

    def escribir_tag(self, tag_id: str, valor: float) -> dict:
        """
        Escribe un valor en un tag (write_tag). Retorna
        {"ok", "tag_id", "valor", "detalle"}; ok=False si el filtro
        determinista rechazo el comando o la escritura fallo.
        """
        ...
