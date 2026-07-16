# -*- coding: utf-8 -*-
"""
tests/scale/test_queue_broker_detection.py — Queue Mode: detección real de
broker (Fase 21, ADR-0019).

Antes de esta fase, `crear_queue_service()` confiaba en que construir un
cliente `Celery(broker=...)` fallaría si el broker no respondía -- pero el
cliente Celery es LAZY (no conecta al construirse). Este test demuestra que
`_broker_disponible()` hace un PING real y que `crear_queue_service()`
recae en modo local cuando ese ping falla, incluso si `AGENTDESK_QUEUE_URL`
está seteada.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from core.services import queue_service


class TestDeteccionDeBroker(unittest.TestCase):

    def test_01_sin_env_var_modo_local(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTDESK_QUEUE_URL", None)
            servicio = queue_service.crear_queue_service()
        self.assertIsInstance(servicio, queue_service.LocalQueueService)
        self.assertNotIsInstance(servicio, queue_service.CeleryQueueService)

    def test_02_broker_configurado_pero_no_responde_ping_modo_local(self):
        """Env var seteada, pero el ping a Redis falla -- debe degradar a local
        SIN intentar construir el cliente Celery."""
        with patch.dict(os.environ, {"AGENTDESK_QUEUE_URL": "redis://host-inexistente:6379/0"}):
            with patch.object(queue_service, "_broker_disponible", return_value=False):
                servicio = queue_service.crear_queue_service()
        self.assertIsInstance(servicio, queue_service.LocalQueueService)
        self.assertNotIsInstance(servicio, queue_service.CeleryQueueService)

    def test_03_broker_responde_ping_pero_celery_no_instalado_modo_local(self):
        """Ping OK pero el import de celery falla -- fallback local con aviso,
        no una excepcion sin manejar."""
        with patch.dict(os.environ, {"AGENTDESK_QUEUE_URL": "redis://localhost:6379/0"}):
            with patch.object(queue_service, "_broker_disponible", return_value=True):
                with patch.object(queue_service, "CeleryQueueService", side_effect=ImportError("no celery")):
                    servicio = queue_service.crear_queue_service()
        self.assertIsInstance(servicio, queue_service.LocalQueueService)

    def test_04_broker_disponible_hace_ping_real_no_solo_construye_cliente(self):
        """`_broker_disponible` debe intentar un PING -- no solo instanciar
        el cliente redis (que es igual de lazy que Celery)."""
        cliente_fake = MagicMock()
        cliente_fake.ping.return_value = True
        modulo_redis_fake = MagicMock()
        modulo_redis_fake.Redis.from_url.return_value = cliente_fake

        with patch.dict("sys.modules", {"redis": modulo_redis_fake}):
            resultado = queue_service._broker_disponible("redis://localhost:6379/0")

        self.assertTrue(resultado)
        cliente_fake.ping.assert_called_once()

    def test_05_broker_disponible_ping_falla_retorna_false(self):
        cliente_fake = MagicMock()
        cliente_fake.ping.side_effect = ConnectionError("conexion rechazada")
        modulo_redis_fake = MagicMock()
        modulo_redis_fake.Redis.from_url.return_value = cliente_fake

        with patch.dict("sys.modules", {"redis": modulo_redis_fake}):
            resultado = queue_service._broker_disponible("redis://localhost:6379/0")

        self.assertFalse(resultado)

    def test_06_broker_disponible_sin_paquete_redis_retorna_false(self):
        with patch.dict("sys.modules", {"redis": None}):
            resultado = queue_service._broker_disponible("redis://localhost:6379/0")
        self.assertFalse(resultado)


if __name__ == "__main__":
    unittest.main()
