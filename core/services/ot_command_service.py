"""
core/services/ot_command_service.py — Comando y Control de Bucle Cerrado
(Fase 26, ADR-0024).

Protocolo de seguridad para que un agente ESCRIBA en la planta:

  1. El agente solo PROPONE (proponer): la propuesta pasa el filtro
     determinista del adaptador (limites fisicos) YA en este paso — una
     propuesta insegura ni siquiera llega al operador.
  2. Confirmacion de Operador OBLIGATORIA (Human-in-the-loop): nada sale
     a la red sin aprobar(), que exige rol supervisor+ (verificado en el
     endpoint) y re-valida el filtro — el estado de planta pudo cambiar
     entre la propuesta y la aprobacion.
  3. Las propuestas EXPIRAN (TTL 15 min): una aprobacion tardia sobre un
     diagnostico viejo es en si misma una accion peligrosa.
  4. Todo queda en la auditoria forense (ot_propuesta / ot_comando /
     ot_rechazo) con user_id y resultado — y se difunde por WS al
     dashboard para la bandeja de aprobacion.

Los adaptadores llegan por INYECCION (registrar_adaptador) desde la capa
de composicion — este servicio jamas importa core.adapters (regla de
imports del guardian, ADR-0002).
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time

logger = logging.getLogger(__name__)

TTL_PROPUESTA_S = 15 * 60   # 15 min: pasado esto, la aprobacion se rechaza


class OTCommandService:
    """Bandeja de propuestas de comando OT con aprobacion humana obligatoria."""

    def __init__(self) -> None:
        self._adaptadores: dict[str, object] = {}
        self._propuestas: dict[int, dict] = {}
        self._ids = itertools.count(1)
        self._broadcast = None   # inyectado por la composicion (WS opcional)

    # ── Composicion ───────────────────────────────────────────────────────

    def registrar_adaptador(self, nombre: str, adaptador) -> None:
        """El adaptador debe cumplir ActuationPort (actuadores/escribir_tag)."""
        self._adaptadores[nombre] = adaptador
        logger.info("OT: adaptador de actuacion registrado '%s' (%d tags escribibles)",
                    nombre, len(adaptador.actuadores()))

    def adaptadores(self) -> list[str]:
        return sorted(self._adaptadores)

    def conectar_broadcast(self, broadcast) -> None:
        self._broadcast = broadcast

    async def _difundir(self, tipo: str, payload: dict) -> None:
        if self._broadcast is None:
            return
        try:
            await self._broadcast({"tipo": tipo, **payload})
        except Exception as exc:
            logger.warning("OT: broadcast fallo (%s) — flujo continua", exc)

    def validar(self, adaptador: str, tag_id: str, valor) -> tuple[bool, str]:
        """
        Filtro determinista SIN efectos (Fase 27, [INTENT-SAFETY]): valida
        un comando contra los limites fisicos del adaptador sin proponer
        ni ejecutar nada. Es lo que el Motor de Intencion usa para no
        mostrarle jamas al usuario una accion OT insegura.
        """
        ad = self._adaptadores.get(adaptador)
        if ad is None:
            return False, f"adaptador '{adaptador}' no registrado"
        _act, motivo = ad._validar_comando(tag_id, valor)
        return (motivo == ""), (motivo or "ok")

    # ── Flujo Human-in-the-loop ───────────────────────────────────────────

    def proponer(self, *, adaptador: str, tag_id: str, valor: float,
                 justificacion: str, agente_id: str = "",
                 user_id: str = "anonimo") -> dict:
        """
        Crea una propuesta PENDIENTE de aprobacion. El filtro determinista
        corre AQUI ademas de en la ejecucion — una propuesta fuera de
        limites se rechaza de inmediato y queda auditada.
        """
        ad = self._adaptadores.get(adaptador)
        if ad is None:
            return {"ok": False,
                    "detalle": f"adaptador '{adaptador}' no registrado "
                               f"(disponibles: {self.adaptadores() or 'ninguno'})"}

        _act, motivo = ad._validar_comando(tag_id, valor)
        self._auditar("ot_propuesta", agente_id, user_id,
                      f"{adaptador}.{tag_id}={valor} — {justificacion}",
                      exitoso=not motivo, detalle=motivo or "pendiente de aprobacion")
        if motivo:
            logger.warning("AUDITORIA_SEGURIDAD: propuesta OT RECHAZADA en origen "
                           "— %s.%s=%r (%s)", adaptador, tag_id, valor, motivo)
            return {"ok": False, "detalle": f"rechazada por filtro de seguridad: {motivo}"}

        prop_id = next(self._ids)
        propuesta = {
            "id": prop_id, "adaptador": adaptador, "tag_id": tag_id,
            "valor": float(valor), "justificacion": justificacion[:500],
            "agente_id": agente_id, "user_id": user_id,
            "estado": "pendiente", "creada": time.time(),
            "expira": time.time() + TTL_PROPUESTA_S,
            "resuelta_por": None, "resultado": None,
        }
        self._propuestas[prop_id] = propuesta
        logger.info("OT: propuesta #%d creada — %s.%s=%s (agente=%s)",
                    prop_id, adaptador, tag_id, valor, agente_id or "?")
        try:
            asyncio.get_running_loop().create_task(
                self._difundir("ot_propuesta", {"propuesta": dict(propuesta)}))
        except RuntimeError:
            pass   # sin event loop (tests sincronos): el WS es best-effort
        return {"ok": True, "propuesta_id": prop_id,
                "detalle": "pendiente de aprobacion del operador"}

    def aprobar(self, propuesta_id: int, *, user_id: str) -> dict:
        """
        Confirmacion de Operador: ejecuta el comando. El RBAC supervisor+
        se verifica en el endpoint ANTES de llegar aqui; este metodo
        re-valida expiracion y filtro, y ejecuta via el adaptador.
        """
        p = self._propuestas.get(propuesta_id)
        if p is None or p["estado"] != "pendiente":
            return {"ok": False, "detalle": "propuesta inexistente o ya resuelta"}

        if time.time() > p["expira"]:
            p["estado"], p["resuelta_por"] = "expirada", user_id
            self._auditar("ot_rechazo", p["agente_id"], user_id,
                          f"{p['adaptador']}.{p['tag_id']}={p['valor']}",
                          exitoso=False, detalle="propuesta expirada (TTL)")
            return {"ok": False, "detalle": "propuesta expirada — vuelve a diagnosticar"}

        ad = self._adaptadores.get(p["adaptador"])
        if ad is None:
            return {"ok": False, "detalle": "adaptador ya no disponible"}

        resultado = ad.escribir_tag(p["tag_id"], p["valor"])   # re-valida el filtro
        p["estado"] = "ejecutada" if resultado["ok"] else "fallida"
        p["resuelta_por"], p["resultado"] = user_id, resultado
        self._auditar(
            "ot_comando", p["agente_id"], user_id,
            f"{p['adaptador']}.{p['tag_id']}={p['valor']} — aprobada por {user_id}",
            exitoso=resultado["ok"], detalle=str(resultado.get("detalle", "")),
        )
        try:
            asyncio.get_running_loop().create_task(
                self._difundir("ot_resultado", {"propuesta": dict(p)}))
        except RuntimeError:
            pass
        return {"ok": resultado["ok"], "propuesta": dict(p)}

    def rechazar(self, propuesta_id: int, *, user_id: str, motivo: str = "") -> dict:
        p = self._propuestas.get(propuesta_id)
        if p is None or p["estado"] != "pendiente":
            return {"ok": False, "detalle": "propuesta inexistente o ya resuelta"}
        p["estado"], p["resuelta_por"] = "rechazada", user_id
        self._auditar("ot_rechazo", p["agente_id"], user_id,
                      f"{p['adaptador']}.{p['tag_id']}={p['valor']}",
                      exitoso=True, detalle=motivo or "rechazada por el operador")
        return {"ok": True, "propuesta": dict(p)}

    def listar(self, estado: str | None = None) -> list[dict]:
        props = [dict(p) for p in self._propuestas.values()
                 if estado is None or p["estado"] == estado]
        return sorted(props, key=lambda p: p["id"], reverse=True)

    # ── Auditoria forense ─────────────────────────────────────────────────

    @staticmethod
    def _auditar(tipo: str, agente_id: str, user_id: str,
                 comando: str, *, exitoso: bool, detalle: str) -> None:
        from core.telemetry_otel import medir_paso
        try:
            from core.services.audit_service import registrar_interaccion
            with medir_paso("ot.auditar", tipo=tipo):
                registrar_interaccion(
                    tipo=tipo, agente_id=agente_id or "operador",
                    prompt=comando, respuesta=detalle,
                    user_id=user_id, exitoso=exitoso,
                    veredicto_guardrail="aprobado" if exitoso else "abortado_guardrails",
                )
        except Exception as exc:
            logger.warning("OT: auditoria no registrada (%s) — flujo continua", exc)


ot_service = OTCommandService()
