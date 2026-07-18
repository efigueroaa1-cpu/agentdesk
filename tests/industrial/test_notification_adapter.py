"""
tests/industrial/test_notification_adapter.py — Adaptadores de notificación
(Fase 29, ADR-0027). Test espejo exigido por [OT-TEST] para todo
core/adapters/*_adapter.py.

Nada sale a la red: _post_json se parchea y se inspecciona el payload que
cada adaptador construye. Se cubre además el contrato best-effort (sin
credenciales → False; excepción del transporte → False, jamás propaga).
"""
import unittest
from unittest import mock

from core.adapters import notification_adapter as na
from core.adapters.notification_adapter import (
    SlackWebhookAdapter,
    WhatsAppCloudAdapter,
    _post_json,
)
from core.ports.notification_port import NotificationPort


class TestPostJson(unittest.TestCase):
    def test_rechaza_esquemas_no_https(self):
        for url in ("http://inseguro.example/hook", "file:///C:/x", "ftp://x"):
            with self.assertRaises(ValueError):
                _post_json(url, {})


class TestSlackAdapter(unittest.TestCase):
    def test_cumple_el_protocolo(self):
        self.assertIsInstance(SlackWebhookAdapter(webhook_url=""), NotificationPort)

    def test_sin_webhook_no_configurado_y_enviar_false(self):
        # webhook_url="" es falsy -> caeria al entorno; se vacia tambien ahi
        with mock.patch.dict("os.environ", {"AGENTDESK_SLACK_WEBHOOK": ""}):
            adaptador = SlackWebhookAdapter(webhook_url="")
        self.assertFalse(adaptador.configurado)
        self.assertFalse(adaptador.enviar("t", "m"))

    def test_payload_y_url_correctos(self):
        adaptador = SlackWebhookAdapter(webhook_url="https://hooks.slack.example/T/B/x")
        with mock.patch.object(na, "_post_json", return_value=200) as post:
            self.assertTrue(adaptador.enviar(
                "Guardrails: fallos consecutivos", "fallos=3",
                severidad="critica",
            ))
        url, payload = post.call_args.args
        self.assertEqual(url, "https://hooks.slack.example/T/B/x")
        self.assertIn("CRITICA", payload["text"])
        self.assertIn("Guardrails: fallos consecutivos", payload["text"])
        self.assertIn("fallos=3", payload["text"])

    def test_status_no_2xx_es_false(self):
        adaptador = SlackWebhookAdapter(webhook_url="https://hooks.slack.example/x")
        with mock.patch.object(na, "_post_json", return_value=500):
            self.assertFalse(adaptador.enviar("t", "m"))

    def test_excepcion_del_transporte_no_propaga(self):
        adaptador = SlackWebhookAdapter(webhook_url="https://hooks.slack.example/x")
        with mock.patch.object(na, "_post_json", side_effect=OSError("timeout")):
            self.assertFalse(adaptador.enviar("t", "m"))

    def test_lee_webhook_del_entorno(self):
        with mock.patch.dict("os.environ",
                             {"AGENTDESK_SLACK_WEBHOOK": "https://hooks.slack.example/env"}):
            self.assertTrue(SlackWebhookAdapter().configurado)


class TestWhatsAppAdapter(unittest.TestCase):
    def _adaptador(self):
        return WhatsAppCloudAdapter(token="tok-test", phone_id="12345",
                                    destino="5215500000000")

    def test_cumple_el_protocolo(self):
        self.assertIsInstance(self._adaptador(), NotificationPort)

    def test_sin_credenciales_completas_enviar_false(self):
        for kwargs in (
            {"token": "", "phone_id": "1", "destino": "2"},
            {"token": "t", "phone_id": "", "destino": "2"},
            {"token": "t", "phone_id": "1", "destino": ""},
        ):
            adaptador = WhatsAppCloudAdapter(**kwargs)
            self.assertFalse(adaptador.configurado)
            self.assertFalse(adaptador.enviar("t", "m"))

    def test_payload_url_y_bearer_correctos(self):
        adaptador = self._adaptador()
        with mock.patch.object(na, "_post_json", return_value=200) as post:
            self.assertTrue(adaptador.enviar("Alerta", "p95=12s"))
        url, payload, headers = post.call_args.args
        self.assertEqual(url, "https://graph.facebook.com/v19.0/12345/messages")
        self.assertEqual(payload["messaging_product"], "whatsapp")
        self.assertEqual(payload["to"], "5215500000000")
        self.assertIn("Alerta", payload["text"]["body"])
        self.assertEqual(headers["Authorization"], "Bearer tok-test")

    def test_excepcion_del_transporte_no_propaga(self):
        adaptador = self._adaptador()
        with mock.patch.object(na, "_post_json", side_effect=OSError("dns")):
            self.assertFalse(adaptador.enviar("t", "m"))


if __name__ == "__main__":
    unittest.main()
