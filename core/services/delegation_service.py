"""
core/services/delegation_service.py — Delegación Cognitiva Runtime (ADR-0011).

Implementa los puertos Speak/Listen: un agente en medio de una conversación
de tool-calling puede pedirle ayuda a OTRO agente del mismo orquestador,
recibir su respuesta, y seguir su propio flujo con ese resultado. Ambos
lados de la delegación quedan auditados en auditoria_ia (ADR-0007) — la
traza de quién delegó y quién resolvió se conserva completa.

Freno estructural contra ciclos: el agente delegado responde vía
`chat_libre` (sin tool-calling), por lo que NO tiene acceso a la
herramienta `consultar_a_otro_agente` — estructuralmente no puede volver a
delegar. No hace falta un contador de profundidad: la propia superficie de
herramientas disponibles ya lo impide.
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

MAX_LARGO_MENSAJE = 4000


class DelegationService:
    """Implementa SpeakPort y ListenPort sobre el Orquestador en memoria."""

    def __init__(self, get_orquestador: Callable[[], object | None]):
        self._get_orquestador = get_orquestador

    async def speak(self, origen_id: str, destino_id: str, mensaje: str,
                     user_id: str = "anonimo") -> str:
        """origen_id emite `mensaje` hacia destino_id y retorna lo que responda."""
        orq = self._get_orquestador()
        if orq is None or not hasattr(orq, "agentes"):
            return "No se pudo delegar: orquestador no disponible."
        if destino_id == origen_id:
            return "No se puede delegar una subtarea a uno mismo."
        if destino_id not in orq.agentes:
            return f"No existe el agente '{destino_id}' para delegar."

        mensaje = (mensaje or "")[:MAX_LARGO_MENSAJE]
        try:
            respuesta = await self.listen(destino_id, origen_id, mensaje, user_id)
        except Exception as exc:
            logger.warning("Delegacion '%s'->'%s' fallo: %s", origen_id, destino_id, exc)
            respuesta = f"El agente '{destino_id}' no pudo resolver la subtarea delegada."
        self._auditar(origen_id, "delegado", f"[delego a {destino_id}] {mensaje}",
                       respuesta, user_id)
        return respuesta

    async def listen(self, destino_id: str, origen_id: str, mensaje: str,
                      user_id: str = "anonimo") -> str:
        """destino_id procesa la subtarea delegada por origen_id y responde."""
        orq    = self._get_orquestador()
        agente = orq.agentes.get(destino_id) if orq and hasattr(orq, "agentes") else None
        if agente is None:
            return f"No existe el agente '{destino_id}'."

        sesion_delegada = f"delegacion:{origen_id}->{destino_id}"
        respuesta = await agente.chat_libre(
            mensaje, sesion_id=sesion_delegada, agente_id_clave=destino_id, user_id=user_id,
        )
        self._auditar(destino_id, "resuelto", f"[delegado por {origen_id}] {mensaje}",
                       respuesta, user_id)
        return respuesta

    @staticmethod
    def _auditar(agente_id: str, tipo: str, prompt: str, respuesta: str, user_id: str) -> None:
        """Traza forense best-effort de CADA lado de la delegación (ADR-0007/0011)."""
        from core.services.audit_service import registrar_interaccion
        registrar_interaccion(
            tipo="delegacion", agente_id=agente_id, prompt=prompt, respuesta=respuesta,
            user_id=user_id, contexto=tipo, veredicto_guardrail="no_aplica",
        )
