"""
core/metrics_prometheus.py — Métricas Prometheus (ADR-0014; FinOps IA
extendido en Fase 19, ADR-0017).

Expone contadores/histogramas de interacciones, tokens, costo USD estimado,
duración y estado de los circuitos LLM — la base del endpoint GET /metrics
para diagnosticar cuellos de botella y auditar gasto de IA sin depurar código.

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
        "agentdesk_tokens_estimados", "Tokens por interaccion (exactos del proveedor o chars/4)",
        ["agente_id"], registry=REGISTRO,
        buckets=(50, 100, 250, 500, 1000, 2000, 4000, 8000),
    )
    TOKENS_TOTAL = Counter(
        "agentdesk_tokens_total",
        "Tokens acumulados por proveedor, distinguiendo exactos de estimados (ADR-0017)",
        ["proveedor", "exacto"], registry=REGISTRO,
    )
    COSTO_USD_TOTAL = Counter(
        "agentdesk_costo_usd_total",
        "Costo USD acumulado estimado por proveedor (tarifa aproximada, ADR-0017 — no es factura real)",
        ["proveedor"], registry=REGISTRO,
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
                          tokens: int = 0, duracion_s: float | None = None,
                          tokens_exactos: bool = False, costo_usd: float = 0.0,
                          proveedor: str = "") -> None:
    """Best-effort: nunca debe romper la interacción que está midiendo."""
    if not _DISPONIBLE:
        return
    try:
        INTERACCIONES_TOTAL.labels(tipo=tipo or "desconocido", exitoso=str(bool(exitoso))).inc()
        if tokens:
            TOKENS_ESTIMADOS.labels(agente_id=agente_id or "desconocido").observe(tokens)
            TOKENS_TOTAL.labels(proveedor=proveedor or "desconocido",
                                exacto=str(bool(tokens_exactos))).inc(tokens)
        if costo_usd:
            COSTO_USD_TOTAL.labels(proveedor=proveedor or "desconocido").inc(costo_usd)
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
