"""
core/services/notification_service.py — Despachador de alertas proactivas
(Fase 29, ADR-0027).

alert_service (Fase 20) DETECTA violaciones de SLOs (fallos consecutivos de
guardrails, latencia p95 degradada, circuit breakers abiertos) pero solo las
escribía en el log: si nadie mira el dashboard, nadie se entera. Este
servicio cierra el bucle: recibe los eventos detectados y los reparte a los
canales registrados (Slack/WhatsApp vía NotificationPort), con enfriamiento
por tipo para no bombardear al operador — el monitor corre cada 60 s; una
alerta persistente se reenvía como máximo cada COOLDOWN_S.

Principios:
  - Hexagonal (ADR-0004): aquí NO se importan adaptadores; los canales se
    inyectan con registrar_canal() desde core/api/__init__.py (bordes).
  - Best-effort: un canal caído se loguea y no bloquea a los demás ni al
    loop de alertas.
  - Sin canales registrados el evento sigue quedando en el log crítico
    (AUDITORIA_SEGURIDAD lo emite alert_service) — cero pérdida de señal.
"""
from __future__ import annotations

import logging
import time

from core.ports.notification_port import NotificationPort

logger = logging.getLogger(__name__)

# Reenvío de un mismo TIPO de alerta como máximo cada 10 min (el chequeo de
# SLOs corre cada 60 s: sin cooldown, una degradación sostenida generaría
# 10 mensajes idénticos en 10 minutos).
COOLDOWN_S = 600.0

_TITULOS = {
    "guardrails_consecutivos": "Guardrails: fallos consecutivos en el pipeline",
    "latencia_p95": "LLM: latencia p95 degradada",
    "circuito_abierto": "LLM: proveedor con circuit breaker abierto",
}


class NotificationService:
    def __init__(self) -> None:
        self._canales: list[NotificationPort] = []
        self._ultimo_envio: dict[str, float] = {}  # tipo -> time.monotonic()
        self._contadores: dict[str, int] = {
            "enviadas": 0, "suprimidas_cooldown": 0, "fallidas": 0,
        }

    # ── Composición (solo desde los bordes) ────────────────────────────────

    def registrar_canal(self, canal: NotificationPort) -> None:
        self._canales.append(canal)
        logger.info(
            "NOTIFICACIONES: canal '%s' registrado",
            getattr(canal, "nombre", type(canal).__name__),
        )

    def canales(self) -> list[str]:
        return [getattr(c, "nombre", type(c).__name__) for c in self._canales]

    def estado(self) -> dict:
        return {"canales": self.canales(), **self._contadores}

    # ── Despacho ───────────────────────────────────────────────────────────

    def notificar(self, evento: dict) -> int:
        """
        Despacha un evento de alert_service ({tipo, detalle}) a todos los
        canales. Retorna cuántos canales lo aceptaron (0 si fue suprimido
        por cooldown o no hay canales).
        """
        from core.telemetry_otel import medir_paso

        tipo = str(evento.get("tipo", "desconocido"))
        ahora = time.monotonic()
        previo = self._ultimo_envio.get(tipo)
        if previo is not None and (ahora - previo) < COOLDOWN_S:
            self._contadores["suprimidas_cooldown"] += 1
            return 0
        if not self._canales:
            return 0

        titulo = _TITULOS.get(tipo, f"Alerta industrial: {tipo}")
        detalle = evento.get("detalle") or {}
        mensaje = "; ".join(f"{k}={v}" for k, v in detalle.items()) or tipo

        aceptadas = 0
        with medir_paso("notificacion.despachar", tipo=tipo):
            for canal in self._canales:
                try:
                    if canal.enviar(titulo, mensaje, severidad="critica",
                                    metadatos=detalle):
                        aceptadas += 1
                    else:
                        self._contadores["fallidas"] += 1
                except Exception as exc:  # el puerto promete no lanzar; cinturón igual
                    self._contadores["fallidas"] += 1
                    logger.warning(
                        "NOTIFICACIONES: canal '%s' lanzo excepcion (%s)",
                        getattr(canal, "nombre", "?"), exc,
                    )

        # El cooldown se marca por INTENTO (hubo canales), no por éxito:
        # un webhook roto no debe convertirse en un martilleo cada 60 s.
        self._ultimo_envio[tipo] = ahora
        self._contadores["enviadas"] += aceptadas
        return aceptadas


# Singleton de módulo (mismo patrón que ot_service / llm_service).
notification_service = NotificationService()
