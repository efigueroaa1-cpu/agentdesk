"""
core/metrics_prometheus.py — Métricas Prometheus (ADR-0014).

Expone contadores/histogramas de interacciones, tokens, duración y estado
de los circuitos LLM — la base del endpoint GET /metrics para diagnosticar
cuellos de botella sin depurar código.

Best-effort: si `prometheus_client` no está instalado, todas las funciones
degradan a no-ops (o a un payload de aviso en generar_exposicion) — nunca
rompen la interacción que están midiendo.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
    from prometheus_client import CONTENT_TYPE_LATEST as _CONTENT_TYPE_LATEST
    _DISPONIBLE = True
except ImportError:
    _DISPONIBLE = False
    _CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

if _DISPONIBLE:
    REGISTRO = CollectorRegistry()

    INTERACCIONES_TOTAL = Counter(
        "agentdesk_interacciones_total", "Interacciones de agentes procesadas",
        ["tipo", "exitoso"], registry=REGISTRO,
    )
    TOKENS_ESTIMADOS = Histogram(
        "agentdesk_tokens_estimados", "Tokens estimados por interaccion (ADR-0007: chars/4)",
        ["agente_id"], registry=REGISTRO,
        buckets=(50, 100, 250, 500, 1000, 2000, 4000, 8000),
    )
    DURACION_INTERACCION_S = Histogram(
        "agentdesk_interaccion_duracion_segundos", "Duracion total de una interaccion",
        ["tipo"], registry=REGISTRO,
    )
    CIRCUITO_LLM_ACTIVO = Gauge(
        "agentdesk_circuito_llm_activo",
        "1 si el circuito del proveedor esta CLOSED (disponible), 0 si OPEN",
        ["proveedor"], registry=REGISTRO,
    )


def registrar_interaccion(tipo: str, exitoso: bool, agente_id: str,
                          tokens: int = 0, duracion_s: float | None = None) -> None:
    """Best-effort: nunca debe romper la interacción que está midiendo."""
    if not _DISPONIBLE:
        return
    try:
        INTERACCIONES_TOTAL.labels(tipo=tipo or "desconocido", exitoso=str(bool(exitoso))).inc()
        if tokens:
            TOKENS_ESTIMADOS.labels(agente_id=agente_id or "desconocido").observe(tokens)
        if duracion_s is not None:
            DURACION_INTERACCION_S.labels(tipo=tipo or "desconocido").observe(duracion_s)
    except Exception as exc:
        logger.warning("metrics_prometheus: fallo al registrar interaccion (%s)", exc)


def actualizar_circuitos_llm(estado_circuitos: dict) -> None:
    """Refleja el estado OPEN/CLOSED de cada proveedor LLM como gauge (0/1)."""
    if not _DISPONIBLE:
        return
    try:
        for proveedor, info in estado_circuitos.items():
            CIRCUITO_LLM_ACTIVO.labels(proveedor=proveedor).set(1 if info.get("activo") else 0)
    except Exception as exc:
        logger.warning("metrics_prometheus: fallo al actualizar circuitos (%s)", exc)


def generar_exposicion() -> tuple[bytes, str]:
    """(payload, content_type) listo para servir en GET /metrics."""
    if not _DISPONIBLE:
        return (b"# prometheus_client no instalado en este build\n",
                "text/plain; version=0.0.4")
    try:
        return (generate_latest(REGISTRO), _CONTENT_TYPE_LATEST)
    except Exception as exc:
        logger.warning("metrics_prometheus: fallo al generar exposicion (%s)", exc)
        return (b"# error generando metricas\n", "text/plain; version=0.0.4")
