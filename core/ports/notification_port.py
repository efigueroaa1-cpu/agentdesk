"""
core/ports/notification_port.py — Puerto de notificaciones salientes
(Fase 29, ADR-0027).

Contrato para canales de aviso proactivo (Slack, WhatsApp, correo…).
Los servicios (alert_service → notification_service) solo conocen este
Protocol; los adaptadores concretos viven en
core/adapters/notification_adapter.py y se registran en el arranque
(composición en los bordes, ADR-0004).

Observabilidad: este archivo es un contrato puro (sin imports fuera de
stdlib, regla de capas ADR-0002); la instrumentación real —
core.telemetry_otel.medir_paso("notificacion.despachar") — vive en el
despachador notification_service, no aquí.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class NotificationPort(Protocol):
    """Canal de salida para alertas críticas de SLOs industriales.

    Implementaciones best-effort: enviar() retorna True si el canal aceptó
    el mensaje y False ante cualquier problema (sin credenciales, red caída,
    respuesta no-2xx). JAMÁS debe propagar excepciones al despachador.
    """

    nombre: str

    def enviar(
        self,
        titulo: str,
        mensaje: str,
        severidad: str = "critica",
        metadatos: dict | None = None,
    ) -> bool:
        """Envía la notificación. True si el canal la aceptó."""
        ...
