"""
core/telemetry_history.py — Historial en memoria de telemetría OT
(Fase 23, ADR-0021).

Hasta esta fase la telemetría industrial era EFÍMERA: cada MetricEvent se
difundía por WebSocket (con Cola Resiliente por suscriptor, ADR-0012) y se
descartaba — "las últimas 1000 métricas" no existían en ninguna parte. El
Gemelo Digital (correlación OT↔negocio, análisis de riesgo) necesita ese
historial reciente.

Mismo patrón que `core/telemetry_otel._spans_recientes`: un ring buffer en
memoria del proceso, sin base de datos — la decisión [DB-CONCURRENCY] de
ADR-0013 prohíbe a los adaptadores de telemetría escribir en la DB, y un
INSERT por tick de sensor sería exactamente la contención que esa regla
evita. Volatilidad aceptada y documentada: el historial se pierde al
reiniciar; el Gemelo Digital razona sobre la ventana reciente, la
trazabilidad de largo plazo sigue siendo trabajo de la auditoría (ADR-0007).

Higiene anti data-poisoning (ADR-0021): los eventos marcados fuera de rango
físico (`metadata.fuera_de_rango_fisico`) NO entran al historial — el
Gemelo Digital nunca razona sobre lecturas físicamente imposibles.
"""
from __future__ import annotations

import threading
from collections import deque

MAX_EVENTOS = 2000

_eventos: deque[dict] = deque(maxlen=MAX_EVENTOS)
_lock = threading.Lock()   # los adaptadores MQTT reciben en hilos propios


def registrar_evento(evento_dict: dict) -> None:
    """Registra un MetricEvent.to_dict() en el historial (best-effort, nunca lanza)."""
    try:
        if (evento_dict.get("metadata") or {}).get("fuera_de_rango_fisico"):
            return   # lecturas envenenadas no alimentan el Gemelo Digital
        with _lock:
            _eventos.append(evento_dict)
    except Exception:
        pass


def eventos_recientes(limit: int = 1000, fuente: str | None = None) -> list[dict]:
    """Últimos `limit` eventos (más viejo primero), filtrable por fuente/sensor."""
    with _lock:
        todos = list(_eventos)
    if fuente:
        todos = [e for e in todos if e.get("fuente") == fuente]
    return todos[-limit:]


def ultimo_por_sensor() -> dict[str, dict]:
    """{sensor_id: ultimo_evento} — la foto actual de la planta."""
    foto: dict[str, dict] = {}
    with _lock:
        for e in _eventos:
            if e.get("fuente"):
                foto[e["fuente"]] = e
    return foto


def limpiar() -> None:
    """Solo para tests: vacía el historial."""
    with _lock:
        _eventos.clear()
