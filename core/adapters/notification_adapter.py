"""
core/adapters/notification_adapter.py — Canales de notificación proactiva
(Fase 29, ADR-0027).

Implementaciones del NotificationPort:
  - SlackWebhookAdapter: POST al Incoming Webhook de Slack
    (AGENTDESK_SLACK_WEBHOOK).
  - WhatsAppCloudAdapter: POST a la Cloud API de Meta
    (AGENTDESK_WHATSAPP_TOKEN + AGENTDESK_WHATSAPP_PHONE_ID +
    AGENTDESK_WHATSAPP_DESTINO, número en formato internacional sin '+').

Credenciales SOLO por variable de entorno (regla [TOOL-SECURITY] de
adaptadores OT — nada embebido en el código versionado). HTTP saliente con
urllib stdlib y esquema https validado (mismo patrón nosec B310 que
web_monitor.py / updater.py). Ambos canales son best-effort: cualquier
excepción se loguea y se traduce a False — jamás rompen el loop de alertas.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0


def _post_json(url: str, payload: dict, headers: dict | None = None) -> int:
    """POST JSON y retorna el status HTTP. Solo admite https:// (B310)."""
    if not url.lower().startswith("https://"):
        raise ValueError("solo se admiten endpoints https://")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # nosec B310 - esquema validado arriba
        return resp.status


class SlackWebhookAdapter:
    """Incoming Webhook de Slack: un solo POST con el texto de la alerta."""

    nombre = "slack"

    def __init__(self, webhook_url: str | None = None) -> None:
        self._url = (webhook_url or os.environ.get("AGENTDESK_SLACK_WEBHOOK", "")).strip()

    @property
    def configurado(self) -> bool:
        return bool(self._url)

    def enviar(
        self,
        titulo: str,
        mensaje: str,
        severidad: str = "critica",
        metadatos: dict | None = None,
    ) -> bool:
        if not self._url:
            return False
        payload = {"text": f"[AgentDesk · {severidad.upper()}] {titulo}\n{mensaje}"}
        try:
            status = _post_json(self._url, payload)
            return 200 <= status < 300
        except Exception as exc:
            logger.warning("SLACK: envio fallido (%s)", exc)
            return False


class WhatsAppCloudAdapter:
    """Cloud API de Meta (graph.facebook.com): mensaje de texto simple."""

    nombre = "whatsapp"
    _GRAPH_BASE = "https://graph.facebook.com/v19.0"

    def __init__(
        self,
        token: str | None = None,
        phone_id: str | None = None,
        destino: str | None = None,
    ) -> None:
        self._token = (token or os.environ.get("AGENTDESK_WHATSAPP_TOKEN", "")).strip()
        self._phone_id = (phone_id or os.environ.get("AGENTDESK_WHATSAPP_PHONE_ID", "")).strip()
        self._destino = (destino or os.environ.get("AGENTDESK_WHATSAPP_DESTINO", "")).strip()

    @property
    def configurado(self) -> bool:
        return bool(self._token and self._phone_id and self._destino)

    def enviar(
        self,
        titulo: str,
        mensaje: str,
        severidad: str = "critica",
        metadatos: dict | None = None,
    ) -> bool:
        if not self.configurado:
            return False
        url = f"{self._GRAPH_BASE}/{self._phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": self._destino,
            "type": "text",
            "text": {"body": f"[AgentDesk · {severidad}] {titulo} — {mensaje}"},
        }
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            status = _post_json(url, payload, headers)
            return 200 <= status < 300
        except Exception as exc:
            logger.warning("WHATSAPP: envio fallido (%s)", exc)
            return False
