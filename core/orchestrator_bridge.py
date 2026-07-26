# -*- coding: utf-8 -*-
"""
core/orchestrator_bridge.py — Integracion con el CommandBridge (senales externas).

Extraido de core/orchestrator.py (2026-07-26, Strangler Fig v1.3, orchestrator
incremento 3/N): procesar_comandos (loop background que consume la
asyncio.Queue del CommandBridge) + _despachar (RELOAD_CONFIG / CREAR_AGENTE /
ELIMINAR_AGENTE / ACTUALIZAR_AGENTE / RELOAD_FINANZAS) + _recargar_finanzas.
Mixin: Orquestador hereda estos metodos; usan self._bridge y los metodos de
CRUD del RegistryMixin (self.reload_agente/crear/eliminar/actualizar).
Las constantes de comando vienen de core.command_bridge (sin ciclo).
Cubierto por tests/scale/test_resource_guard.py.
"""
import logging

from core.command_bridge import (
    Command, RELOAD_CONFIG, CREAR_AGENTE, ELIMINAR_AGENTE,
    ACTUALIZAR_AGENTE, RELOAD_FINANZAS,
)

logger = logging.getLogger(__name__)


class OrquestadorBridgeMixin:
    """Recepcion y despacho de comandos del CommandBridge (ver core/orchestrator.py)."""

    # ── Loop de consumo de comandos ────────────────────────────────────────────

    async def procesar_comandos(self) -> None:
        """
        Tarea background: consume comandos del CommandBridge hasta ser cancelada.
        Se lanza con asyncio.create_task() desde main.py.
        """
        if self._bridge is None:
            return

        try:
            async for cmd in self._bridge.consume():
                await self._despachar(cmd)
        except asyncio.CancelledError:
            logger.info("procesar_comandos: tarea cancelada limpiamente.")

    async def _despachar(self, cmd: Command) -> None:
        """Enruta cada comando al handler correspondiente."""
        if cmd.tipo == RELOAD_CONFIG:
            agente_id    = cmd.payload.get("agente_id")
            actualizados = self.reload_agente(agente_id)
            logger.info(
                "RELOAD_CONFIG aplicado",
                extra={"agente_id": agente_id or "todos", "actualizados": actualizados},
            )
        elif cmd.tipo == CREAR_AGENTE:
            await self.crear_nuevo_agente(cmd.payload)
        elif cmd.tipo == ELIMINAR_AGENTE:
            await self.eliminar_agente(cmd.payload.get("agente_id", ""))
        elif cmd.tipo == ACTUALIZAR_AGENTE:
            await self.actualizar_agente(
                cmd.payload.get("agente_id", ""),
                cmd.payload.get("data", {}),
            )
        elif cmd.tipo == RELOAD_FINANZAS:
            await self._recargar_finanzas(cmd.payload)
        else:
            logger.warning("Comando desconocido ignorado: %s", cmd.tipo)

    async def _recargar_finanzas(self, payload: dict) -> None:
        """
        Actualiza el presupuesto de un agente en caliente sin interrumpir tareas.

        Flujo con rollback Pydantic:
          1. Extrae `agente_id` y `presupuesto` del payload.
          2. Valida presupuesto con PresupuestoConfig.model_validate().
          3. Si pasa: actualiza agent.config["presupuesto"] en memoria y lanza análisis.
          4. Si falla: registra el error y mantiene el estado anterior (rollback implícito).
        """
        from pydantic import ValidationError
        from core.schemas import PresupuestoConfig
        from core.finance import motor_financiero

        agente_id    = payload.get("agente_id")
        presupuesto_raw = payload.get("presupuesto")

        if not agente_id or not presupuesto_raw:
            logger.error("RELOAD_FINANZAS: payload incompleto — se requieren agente_id y presupuesto")
            return

        if agente_id not in self.agentes:
            logger.error("RELOAD_FINANZAS: agente '%s' no existe en el orquestador.", agente_id)
            return

        # Validación Pydantic — rollback implícito si falla (no se toca el agente)
        try:
            presupuesto = PresupuestoConfig.model_validate(presupuesto_raw)
        except ValidationError as e:
            logger.error(
                "RELOAD_FINANZAS rechazado para '%s' — validación fallida. Estado anterior mantenido.",
                agente_id,
                extra={"agente": agente_id, "error": str(e)},
            )
            return

        # Aplicar en memoria al agente (no interrumpe tareas en curso)
        ag = self.agentes[agente_id]
        ag.config["presupuesto"] = presupuesto.model_dump(mode="json")

        logger.info(
            "RELOAD_FINANZAS aplicado para '%s': flujo_neto=%.2f %s",
            agente_id, presupuesto.flujo_neto, presupuesto.moneda,
        )

        # Lanzar análisis async sin bloquear el loop de comandos
        asyncio.create_task(
            motor_financiero.analizar_y_persistir(agente_id, presupuesto),
            name=f"finanzas_{agente_id}",
        )
