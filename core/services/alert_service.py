"""
core/services/alert_service.py — Alertas Activas de SLOs Industriales
(Fase 20, ADR-0018).

Observabilidad pasiva (Prometheus/OTel, ADR-0013) le dice a un operador QUE
mirar cuando ya sospecha un problema. Este módulo cierra el otro extremo:
vigila él mismo las métricas ya existentes (`telemetry_otel.spans_recientes`,
`audit_service.consultar`, `llm_service.estado_circuitos`) y emite un evento
`AUDITORIA_SEGURIDAD` crítico apenas se cruza un umbral — sin esperar a que
alguien abra un dashboard.

Tres SLOs, tal como los pidió la fase:
  1. Latencia p95 de generación LLM > 10s.
  2. 3 fallos CONSECUTIVOS de guardrails (interacciones abortadas seguidas).
  3. Un circuit breaker de proveedor abierto de forma continua > 5 minutos.

Principios (mismos que audit_service.py):
  - Best-effort: un chequeo que falla se loggea y no rompe el loop.
  - No hay estado propio que persistir: cada chequeo relee las fuentes de
    verdad ya existentes (spans, auditoría, circuitos) — este módulo no
    duplica datos, solo los interpreta.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

SLO_LATENCIA_P95_S = 10.0
SLO_GUARDRAILS_FALLOS_CONSECUTIVOS = 3
SLO_CIRCUITO_ABIERTO_MAX_S = 300.0   # 5 minutos

INTERVALO_CHEQUEO_S = 60.0

NOMBRE_SPAN_LLM = "llm.generar"


def _percentil(valores: list[float], p: float) -> float | None:
    """Percentil sin dependencias externas (numpy no es requisito del proyecto)."""
    if not valores:
        return None
    ordenados = sorted(valores)
    indice = min(len(ordenados) - 1, max(0, round(p / 100 * (len(ordenados) - 1))))
    return ordenados[indice]


def chequear_latencia_p95(limit: int = 100) -> dict | None:
    """
    SLO 1: p95 de latencia de generación LLM > 10s.
    Lee `telemetry_otel.spans_recientes()`, que guarda `duracion_ms`.
    """
    from core.telemetry_otel import spans_recientes

    spans = [s for s in spans_recientes(limit=limit) if s.get("nombre") == NOMBRE_SPAN_LLM]
    duraciones_s = [s["duracion_ms"] / 1000.0 for s in spans if s.get("duracion_ms") is not None]
    p95 = _percentil(duraciones_s, 95)
    if p95 is None or p95 <= SLO_LATENCIA_P95_S:
        return None

    detalle = {"p95_s": round(p95, 2), "muestras": len(duraciones_s)}
    logger.error(
        "AUDITORIA_SEGURIDAD: SLO de latencia LLM violado — p95=%.2fs > %.1fs (muestras=%d)",
        p95, SLO_LATENCIA_P95_S, len(duraciones_s),
    )
    return {"tipo": "latencia_p95", "detalle": detalle}


def chequear_guardrails_consecutivos(limit: int = SLO_GUARDRAILS_FALLOS_CONSECUTIVOS) -> dict | None:
    """
    SLO 2: 3 fallos de guardrails SEGUIDOS (las N interacciones más recientes,
    sin ninguna exitosa intercalada).
    """
    from core.services import audit_service

    trazas = audit_service.consultar(limit=limit)
    if len(trazas) < SLO_GUARDRAILS_FALLOS_CONSECUTIVOS:
        return None
    recientes = trazas[:SLO_GUARDRAILS_FALLOS_CONSECUTIVOS]
    if not all(t.get("veredicto_guardrail") == "abortado_guardrails" for t in recientes):
        return None

    detalle = {"fallos_consecutivos": SLO_GUARDRAILS_FALLOS_CONSECUTIVOS,
               "agentes": [t.get("agente_id") for t in recientes]}
    logger.error(
        "AUDITORIA_SEGURIDAD: SLO de guardrails violado — %d fallos consecutivos (agentes=%s)",
        SLO_GUARDRAILS_FALLOS_CONSECUTIVOS, detalle["agentes"],
    )
    return {"tipo": "guardrails_consecutivos", "detalle": detalle}


def chequear_circuitos_abiertos() -> list[dict]:
    """
    SLO 3: circuito de un proveedor abierto de forma CONTINUA > 5 minutos.
    Usa `CircuitBreaker.abierto_desde` (Fase 20) vía `estado_circuitos()`.
    """
    from core.services.llm_service import llm_service

    eventos = []
    for proveedor, estado in llm_service.estado_circuitos().items():
        segundos = estado.get("abierto_desde_hace_s") or 0
        if segundos <= SLO_CIRCUITO_ABIERTO_MAX_S:
            continue
        detalle = {"proveedor": proveedor, "abierto_desde_hace_s": segundos}
        logger.error(
            "AUDITORIA_SEGURIDAD: SLO de circuit breaker violado — '%s' abierto "
            "hace %.0fs (> %.0fs)", proveedor, segundos, SLO_CIRCUITO_ABIERTO_MAX_S,
        )
        eventos.append({"tipo": "circuito_abierto", "detalle": detalle})
    return eventos


def chequear_slos() -> list[dict]:
    """Corre los 3 chequeos y retorna la lista de eventos críticos detectados (best-effort)."""
    eventos: list[dict] = []
    for chequeo in (chequear_latencia_p95, chequear_guardrails_consecutivos):
        try:
            evento = chequeo()
            if evento:
                eventos.append(evento)
        except Exception as exc:
            logger.warning("ALERT_SERVICE: chequeo %s fallo (%s)", chequeo.__name__, exc)
    try:
        eventos.extend(chequear_circuitos_abiertos())
    except Exception as exc:
        logger.warning("ALERT_SERVICE: chequeo de circuitos fallo (%s)", exc)
    return eventos


async def iniciar_monitor(intervalo_s: float = INTERVALO_CHEQUEO_S) -> None:
    """
    Loop de fondo (mismo patrón que `kill_switch.iniciar_monitor()`):
    corre `chequear_slos()` cada `intervalo_s` hasta que la tarea se cancele.
    Registrado como `asyncio.create_task()` en `core/api/__init__.py::startup()`.

    Fase 29 (ADR-0027): cada evento detectado se despacha además por los
    canales de notificación registrados (Slack/WhatsApp) — la alerta ya no
    depende de que un operador esté mirando el log o el dashboard.
    """
    from core.services.notification_service import notification_service

    while True:
        try:
            for evento in chequear_slos():
                notification_service.notificar(evento)
        except Exception as exc:
            logger.warning("ALERT_SERVICE: ciclo de monitoreo fallo (%s)", exc)
        try:
            await asyncio.sleep(intervalo_s)
        except asyncio.CancelledError:
            break
