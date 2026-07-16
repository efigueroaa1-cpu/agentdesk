"""
core/telemetry_otel.py — Tracing distribuido con OpenTelemetry (ADR-0014).

Instrumenta cada paso del agente (llamada al LLM, ejecución de herramienta,
guardrail) con spans OTEL estándar — compatible con cualquier backend real
(Jaeger, Tempo, un OTEL Collector) si se configura, y con un exportador en
memoria propio como respaldo para poder diagnosticar cuellos de botella
SIN infraestructura externa (no hay Collector disponible en este entorno
de desarrollo, mismo criterio que Docker/PostgreSQL en fases anteriores).

Detección dinámica (mismo patrón que AGENTDESK_DB_URL, ADR-0005/0013):
  - AGENTDESK_OTEL_ENDPOINT definida -> exporta también vía OTLP/HTTP a un
    Collector real.
  - Sin la variable -> solo el exportador en memoria (SpanRecorder), que
    alimenta GET /diagnostico/tracing.

Best-effort estricto: si `opentelemetry` no está instalado, `medir_paso`
degrada a un no-op — nunca rompe la ejecución del agente por un problema
de observabilidad.
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

_MAX_SPANS_MEMORIA = 200
_spans_recientes: deque[dict] = deque(maxlen=_MAX_SPANS_MEMORIA)

_tracer = None
_otel_disponible = False


def _inicializar() -> None:
    """Configura el TracerProvider una sola vez (lazy, best-effort)."""
    global _tracer, _otel_disponible
    if _tracer is not None:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        resource = Resource(attributes={SERVICE_NAME: "agentdesk"})
        provider = TracerProvider(resource=resource)

        endpoint = os.environ.get("AGENTDESK_OTEL_ENDPOINT", "").strip()
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                provider.add_span_processor(
                    SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
                )
                logger.info("OTEL: exportando spans a Collector real (%s)", endpoint)
            except ImportError:
                logger.warning(
                    "AGENTDESK_OTEL_ENDPOINT definida pero falta "
                    "opentelemetry-exporter-otlp-proto-http — solo memoria."
                )

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("agentdesk")
        _otel_disponible = True
    except ImportError:
        logger.info("opentelemetry no instalado — telemetria en modo no-op.")
        _otel_disponible = False


@contextmanager
def medir_paso(nombre: str, **atributos) -> Iterator[None]:
    """
    Envuelve un paso (llamada LLM, herramienta, guardrail) en un span OTEL
    y en un registro liviano en memoria (para GET /diagnostico/tracing sin
    depender de un Collector externo). Nunca propaga excepciones propias
    de instrumentación — solo re-lanza lo que el bloque envuelto lance.
    """
    _inicializar()
    t0 = time.monotonic()
    excepcion: BaseException | None = None

    span_cm = None
    if _otel_disponible and _tracer is not None:
        try:
            span_cm = _tracer.start_as_current_span(nombre)
            span = span_cm.__enter__()
            for clave, valor in atributos.items():
                try:
                    span.set_attribute(clave, valor)
                except Exception:
                    pass
        except Exception:
            span_cm = None

    try:
        yield
    except BaseException as exc:
        excepcion = exc
        raise
    finally:
        duracion_ms = round((time.monotonic() - t0) * 1000, 2)
        if span_cm is not None:
            try:
                if excepcion is not None:
                    span_cm.__exit__(type(excepcion), excepcion, excepcion.__traceback__)
                else:
                    span_cm.__exit__(None, None, None)
            except Exception:
                pass
        _spans_recientes.append({
            "nombre": nombre,
            "duracion_ms": duracion_ms,
            "exitoso": excepcion is None,
            "atributos": {k: str(v) for k, v in atributos.items()},
        })


def spans_recientes(limit: int = 100) -> list[dict]:
    """Últimos spans capturados en memoria — diagnóstico sin Collector externo."""
    return list(_spans_recientes)[-limit:]
