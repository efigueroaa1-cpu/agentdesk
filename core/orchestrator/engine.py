# -*- coding: utf-8 -*-
"""
core/orchestrator_engine.py — Motor de ejecucion paralela + auditoria batch.

Extraido de core/orchestrator.py (2026-07-26, Strangler Fig v1.3, orchestrator
incremento 1/N): la Opcion 23 (ejecutar_todos_paralelo) con su semaforo,
jitter anti-429, orden de despacho prioritario y traza forense best-effort.
Mixin: Orquestador hereda estos metodos; esperan self.config y self.agentes.
Cubierto por tests/scale/test_paralelo_controlado.py y tests/audit/.
"""
import asyncio
import logging
import random
import time

# Logger bajo "core.orchestrator" (no __name__): el codigo extraido de
# core/orchestrator.py siempre logueo ahi; dashboards y auditoria forense
# filtran por ese nombre (2026-07-27, contrato operacional preservado).
logger = logging.getLogger("core.orchestrator")


class OrquestadorEngineMixin:
    """Ejecucion paralela controlada + _auditar_batch (ver core/orchestrator.py)."""

    # ── Ejecución paralela controlada (2026-07-19) ────────────────────────────

    async def ejecutar_todos_paralelo(
        self,
        tarea: str = "reporte_ventas",
        datos_override: dict | str | None = None,
        max_paralelo: int | None = None,
        timeout_s: float | None = None,
        corrida_id: str | None = None,
    ) -> list[dict | None]:
        """
        Ejecuta realizar_tarea() en TODOS los agentes con control de flujo:

        - Semáforo de `max_agentes_paralelo` (config.json > orquestador):
          una ráfaga de 22 peticiones simultáneas dispara RateLimit/latencia
          en los proveedores, abre los Circuit Breakers y degrada agentes al
          mock — cuyas cifras inventadas aborta el GroundingGuard. Con el
          semáforo, las peticiones salen en tandas que los proveedores toleran.
        - `timeout_tarea_s` por agente (asyncio.wait_for): un agente colgado
          da None sin arrastrar al resto del lote.
        - `datos_override`: entrada consolidada (ej. snapshot de telemetría
          U1-U5) entregada como raw_data a cada agente ANTES de generar.
        - Jitter por saturacion persistente de Groq (2026-07-20): incluso con
          el semaforo, una racha de agentes que preferian Groq y terminan
          degradados (ultimo_proveedor_llm != "groq", canal lateral ADR-0019)
          indica que Groq esta devolviendo 429 en cascada. Tras
          UMBRAL_429_PERSISTENTE degradaciones SEGUIDAS, se espera un jitter
          extra antes de la siguiente llamada — separado del backoff propio
          de la cadena de fallback (ADR-0017), que ya reintenta por llamada
          individual pero no espacia la rafaga completa. Un exito real en
          Groq resetea el contador.
        - `agentes_prioritarios` (config.json > orquestador, lista de ids,
          2026-07-20): cuando la cuota diaria de Groq esta casi agotada, solo
          alcanza para las PRIMERAS llamadas del lote (verificado en vivo:
          Used 99290/100000 — hay margen para ~1 peticion, no 17). Delays
          artificiales entre agentes NO liberan cuota diaria (TPD), asi que
          el unico control real es QUIEN sale primero a pedir lo que queda.
          Los ids listados se DESPACHAN primero (compiten antes por el
          semaforo/cuota); el resto sigue en su orden de config.json. El
          orden de RETORNO no cambia — sigue siendo el de self.agentes, para
          no romper el zip(agentes_cfg, resultados) de main.py.

        Devuelve los resultados en el MISMO orden que self.agentes (orden de
        config.json), alineado con el zip del dashboard de main.py.
        """
        cfg_orq      = self.config.get("orquestador", {}) if isinstance(self.config, dict) else {}
        if max_paralelo is None:
            max_paralelo = cfg_orq.get("max_agentes_paralelo", 4)
            # Modo CPU-only offline (2026-07-28): sin red, todos los agentes caen
            # a Ollama; correr varios a la vez satura el host (CPU/RAM) y congela
            # la Rich Live. Se serializa a 1 -> el 100% del CPU va a un agente por
            # vez, sin colapsar. Solo aplica si NO hubo override explicito.
            try:
                from core.services.llm_service import llm_service
                if not llm_service.hay_conectividad():
                    logger.warning("PARALELO: modo offline detectado -> "
                                   "max_paralelo=1 (CPU-only, inferencia local)")
                    max_paralelo = 1
            except Exception:
                pass   # la deteccion nunca debe romper el lote
        timeout_s    = timeout_s or cfg_orq.get("timeout_tarea_s", 180)
        semaforo     = asyncio.Semaphore(max_paralelo)

        ids_originales = list(self.agentes.keys())
        prioritarios   = [aid for aid in cfg_orq.get("agentes_prioritarios", [])
                          if aid in self.agentes]
        orden_despacho = prioritarios + [aid for aid in ids_originales
                                         if aid not in prioritarios]

        UMBRAL_429_PERSISTENTE = 2
        JITTER_BASE_S          = 1.5
        _saturacion_groq       = {"consecutivos": 0}

        # Checkpoint de corrida (opcional): con corrida_id, los agentes ya
        # completados en una corrida previa interrumpida se leen del checkpoint
        # y no se re-ejecutan. Sin corrida_id el comportamiento no cambia.
        completados: dict = {}
        if corrida_id:
            try:
                from core.repositories.checkpoint_repository import obtener_checkpoints
                completados = obtener_checkpoints(corrida_id)
                if completados:
                    logger.info(
                        "PARALELO: reanudando corrida '%s' — %d/%d agentes ya "
                        "completados (checkpoint)", corrida_id,
                        len(completados), len(self.agentes),
                    )
            except Exception as exc:
                logger.warning("PARALELO: no se pudieron leer checkpoints de '%s' "
                               "(%s) — corrida completa", corrida_id, exc)

        def _persistir_checkpoint(aid: str, resultado: dict | None) -> None:
            if not corrida_id or not resultado:
                return
            if isinstance(resultado, dict) and resultado.get("_api_error"):
                return
            try:
                from core.repositories.checkpoint_repository import guardar_checkpoint
                guardar_checkpoint(corrida_id, aid, resultado)
            except Exception:
                logger.warning("PARALELO: no se pudo guardar checkpoint de '%s' "
                               "(best-effort)", aid, extra={"agente": aid})

        async def _uno(aid: str, agente) -> dict | None:
            if aid in completados:
                logger.info("PARALELO: agente '%s' reanudado desde checkpoint",
                            agente.nombre, extra={"agente": agente.nombre})
                return completados[aid]
            async with semaforo:
                if _saturacion_groq["consecutivos"] >= UMBRAL_429_PERSISTENTE:
                    espera = JITTER_BASE_S + random.uniform(0, 0.5)
                    logger.warning(
                        "PARALELO: 429 persistente en Groq (%d degradaciones seguidas) "
                        "— espaciando %.2fs antes de '%s'",
                        _saturacion_groq["consecutivos"], espera, agente.nombre,
                        extra={"agente": agente.nombre},
                    )
                    await asyncio.sleep(espera)
                _t0 = time.monotonic()
                try:
                    resultado = await asyncio.wait_for(
                        agente.realizar_tarea(tarea, _datos_override=datos_override),
                        timeout=timeout_s,
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        "PARALELO: agente '%s' excedio timeout_tarea_s=%.0fs — descartado",
                        agente.nombre, timeout_s,
                        extra={"agente": agente.nombre},
                    )
                    self._auditar_batch(aid, agente, None, time.monotonic() - _t0,
                                        veredicto="timeout_paralelo")
                    return None

                modelo_preferido = getattr(agente, "modelo", "") or ""
                proveedor_real   = getattr(agente, "ultimo_proveedor_llm", "") or ""
                if modelo_preferido.startswith("groq:") and proveedor_real and proveedor_real != "groq":
                    _saturacion_groq["consecutivos"] += 1
                else:
                    _saturacion_groq["consecutivos"] = 0

                self._auditar_batch(aid, agente, resultado, time.monotonic() - _t0)
                _persistir_checkpoint(aid, resultado)
                return resultado

        logger.info(
            "PARALELO: %d agentes, max_paralelo=%d, timeout=%.0fs%s",
            len(self.agentes), max_paralelo, timeout_s,
            f", prioritarios={prioritarios}" if prioritarios else "",
        )
        # Las tareas se CREAN (y por tanto compiten por el semaforo, en
        # orden FIFO) segun orden_despacho; se recolectan segun
        # ids_originales para que el orden de retorno no cambie.
        tareas = {aid: asyncio.create_task(_uno(aid, self.agentes[aid]))
                 for aid in orden_despacho}
        return await asyncio.gather(*[tareas[aid] for aid in ids_originales])

    @staticmethod
    def _auditar_batch(agente_id: str, agente, resultado: dict | None,
                       duracion_s: float, veredicto: str | None = None) -> None:
        """
        Traza forense best-effort para la Opcion Paralelo (2026-07-21):
        antes de esto, realizar_tarea() en el lote batch (a diferencia del
        chat y de orchestrator_service.ejecutar_tarea, la ejecucion
        individual via HTTP) nunca llamaba a audit_service — las 22
        ejecuciones de cada corrida eran invisibles para el Panel de
        Auditoria. tipo="tarea_batch" las distingue de "tarea" (individual
        via HTTP) sin romper los consumidores existentes que filtran por
        agente_id/user_id. Nunca debe romper el lote: mismo criterio que
        orchestrator_service._auditar.
        """
        if veredicto is None:
            api_error = isinstance(resultado, dict) and resultado.get("_api_error")
            veredicto = "aprobado" if resultado and not api_error else (
                "error_api" if api_error else "abortado_guardrails")
        try:
            from core.services.audit_service import registrar_interaccion
            registrar_interaccion(
                tipo="tarea_batch",
                agente_id=agente_id,
                prompt="reporte_ventas",
                respuesta=(resultado or {}).get("resumen", "") if isinstance(resultado, dict) else "",
                user_id="sistema_batch",
                contexto="opcion_paralelo",
                modelo=getattr(agente, "modelo", "") or "",
                proveedor=getattr(agente, "ultimo_proveedor_llm", "") or "",
                tokens_reales=getattr(agente, "ultimo_tokens_llm", None),
                veredicto_guardrail=veredicto,
                duracion_s=round(duracion_s, 3),
                exitoso=bool(resultado) and not (isinstance(resultado, dict) and resultado.get("_api_error")),
            )
        except Exception:
            logger.warning("PARALELO: no se pudo registrar auditoria de '%s' (best-effort)",
                           agente_id, extra={"agente": agente_id})
