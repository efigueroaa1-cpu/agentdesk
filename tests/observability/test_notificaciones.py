"""
tests/observability/test_notificaciones.py — Despacho proactivo de alertas
(Fase 29, ADR-0027).

Suite espejo de la regla [ALERT-DISPATCH] del Guardián: el despachador
(notification_service) enruta los eventos de SLO detectados por
alert_service hacia los canales NotificationPort, con cooldown por tipo y
tolerancia total a canales caídos. Los adaptadores concretos (Slack/
WhatsApp) tienen su propia suite en tests/industrial/test_notification_adapter.py.
"""
import asyncio
import unittest
from unittest import mock

from core.ports.notification_port import NotificationPort
from core.services.notification_service import (
    COOLDOWN_S,
    NotificationService,
)


class CanalDummy:
    """Canal en memoria que registra todo lo que recibe."""

    def __init__(self, nombre: str = "dummy", acepta: bool = True) -> None:
        self.nombre = nombre
        self.acepta = acepta
        self.enviados: list[dict] = []

    def enviar(self, titulo, mensaje, severidad="critica", metadatos=None) -> bool:
        self.enviados.append({
            "titulo": titulo, "mensaje": mensaje,
            "severidad": severidad, "metadatos": metadatos,
        })
        return self.acepta


class CanalExplosivo:
    """Canal que viola el contrato y lanza: el despachador debe sobrevivir."""

    nombre = "explosivo"

    def enviar(self, titulo, mensaje, severidad="critica", metadatos=None) -> bool:
        raise ConnectionError("red caida")


def _evento(tipo="guardrails_consecutivos", **detalle):
    return {"tipo": tipo, "detalle": detalle or {"fallos_consecutivos": 3}}


class TestPuertoNotificacion(unittest.TestCase):
    def test_canal_dummy_cumple_el_protocolo(self):
        self.assertIsInstance(CanalDummy(), NotificationPort)


class TestDespachador(unittest.TestCase):
    def setUp(self):
        self.svc = NotificationService()

    def test_sin_canales_no_rompe_y_retorna_cero(self):
        self.assertEqual(self.svc.notificar(_evento()), 0)

    def test_sin_canales_no_consume_el_cooldown(self):
        # Si el evento no pudo salir por ningún canal, al registrarse un
        # canal después el MISMO tipo debe poder despacharse de inmediato.
        self.svc.notificar(_evento())
        canal = CanalDummy()
        self.svc.registrar_canal(canal)
        self.assertEqual(self.svc.notificar(_evento()), 1)
        self.assertEqual(len(canal.enviados), 1)

    def test_despacha_a_todos_los_canales(self):
        c1, c2 = CanalDummy("slack"), CanalDummy("whatsapp")
        self.svc.registrar_canal(c1)
        self.svc.registrar_canal(c2)
        self.assertEqual(self.svc.notificar(_evento()), 2)
        self.assertEqual(len(c1.enviados), 1)
        self.assertEqual(len(c2.enviados), 1)
        self.assertIn("Guardrails", c1.enviados[0]["titulo"])
        self.assertIn("fallos_consecutivos=3", c1.enviados[0]["mensaje"])

    def test_cooldown_suprime_el_mismo_tipo(self):
        canal = CanalDummy()
        self.svc.registrar_canal(canal)
        self.assertEqual(self.svc.notificar(_evento()), 1)
        self.assertEqual(self.svc.notificar(_evento()), 0)      # suprimido
        self.assertEqual(len(canal.enviados), 1)
        self.assertEqual(self.svc.estado()["suprimidas_cooldown"], 1)

    def test_cooldown_no_cruza_tipos_distintos(self):
        canal = CanalDummy()
        self.svc.registrar_canal(canal)
        self.svc.notificar(_evento("guardrails_consecutivos"))
        self.assertEqual(self.svc.notificar(_evento("circuito_abierto",
                                                    proveedor="groq")), 1)
        self.assertEqual(len(canal.enviados), 2)

    def test_cooldown_expira(self):
        canal = CanalDummy()
        self.svc.registrar_canal(canal)
        self.svc.notificar(_evento())
        # Simular que el último envío ocurrió hace más de COOLDOWN_S
        tipo = "guardrails_consecutivos"
        self.svc._ultimo_envio[tipo] -= (COOLDOWN_S + 1)
        self.assertEqual(self.svc.notificar(_evento()), 1)
        self.assertEqual(len(canal.enviados), 2)

    def test_canal_explosivo_no_bloquea_a_los_demas(self):
        sano = CanalDummy("sano")
        self.svc.registrar_canal(CanalExplosivo())
        self.svc.registrar_canal(sano)
        self.assertEqual(self.svc.notificar(_evento()), 1)
        self.assertEqual(len(sano.enviados), 1)
        self.assertEqual(self.svc.estado()["fallidas"], 1)

    def test_canal_roto_marca_cooldown_para_no_martillear(self):
        # Todos los canales fallan: el intento igual consume el cooldown
        # (un webhook caído no debe reintentar cada 60 s).
        self.svc.registrar_canal(CanalDummy(acepta=False))
        self.assertEqual(self.svc.notificar(_evento()), 0)
        self.assertEqual(self.svc.notificar(_evento()), 0)
        self.assertEqual(self.svc.estado()["suprimidas_cooldown"], 1)

    def test_estado_reporta_canales_y_contadores(self):
        self.svc.registrar_canal(CanalDummy("slack"))
        estado = self.svc.estado()
        self.assertEqual(estado["canales"], ["slack"])
        for clave in ("enviadas", "suprimidas_cooldown", "fallidas"):
            self.assertIn(clave, estado)


class TestMonitorDespacha(unittest.TestCase):
    """El loop de alert_service enruta los eventos detectados al despachador."""

    def test_iniciar_monitor_despacha_eventos_de_slo(self):
        from core.services import alert_service
        from core.services import notification_service as ns_mod

        canal = CanalDummy("captura")
        ns_mod.notification_service.registrar_canal(canal)
        evento = _evento("circuito_abierto", proveedor="groq",
                         abierto_desde_hace_s=400)
        try:
            with mock.patch.object(alert_service, "chequear_slos",
                                   return_value=[evento]):
                # Cortar el loop tras la primera iteración vía el sleep
                with mock.patch.object(alert_service.asyncio, "sleep",
                                       side_effect=asyncio.CancelledError):
                    asyncio.run(alert_service.iniciar_monitor())
        finally:
            ns_mod.notification_service._canales.remove(canal)
            ns_mod.notification_service._ultimo_envio.clear()

        self.assertEqual(len(canal.enviados), 1)
        self.assertIn("circuit breaker", canal.enviados[0]["titulo"])
        self.assertIn("proveedor=groq", canal.enviados[0]["mensaje"])


if __name__ == "__main__":
    unittest.main()
