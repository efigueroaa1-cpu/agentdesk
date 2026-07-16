"""
core/services/orchestrator_service.py — Motor de Orquestación Puro (ADR-0003).

Lógica de ejecución y conversación extraída de core/api.py: selección de
agente, ejecución de tareas con telemetría y persistencia, chat con
tool-calling (normal y streaming) y comandos de control remoto. Cero FastAPI:
el broadcast WebSocket y los globals del proceso llegan inyectados, y el
streaming se expone como generador de eventos dict que el adaptador HTTP
serializa a SSE.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable

from core import kill_switch
from core.command_bridge import Command, RELOAD_CONFIG

logger = logging.getLogger(__name__)

COMANDOS_REMOTOS_AYUDA = (
    "  Status                 — estado del sistema y agentes cargados\n"
    "  Reiniciar Agente <id>  — recarga la configuración de un agente\n"
    "  Ayuda                  — lista de comandos\n"
)


def _leer_upload_texto(archivo_id: str) -> str | None:
    """Contenido de un archivo subido (para inyectar a realizar_tarea_con_datos)."""
    import json as _json
    from core.path_manager import data_path
    uploads_dir = data_path("uploads")
    meta_path   = uploads_dir / f"{archivo_id}.meta.json"
    if not meta_path.exists():
        return None
    meta  = _json.loads(meta_path.read_text(encoding="utf-8"))
    fpath = uploads_dir / meta["nombre_interno"]
    if not fpath.exists():
        return None
    return fpath.read_bytes().decode("utf-8", errors="replace")[:18_000]


class OrchestratorService:
    """Implementación de core.ports.orchestrator_port.OrchestratorServicePort."""

    def __init__(
        self,
        get_orquestador: Callable[[], Any],
        get_bridge: Callable[[], Any],
        broadcast: Callable[[dict], Awaitable[None]],
    ):
        self._get_orquestador = get_orquestador
        self._get_bridge      = get_bridge
        self._broadcast       = broadcast

    # ── Selección de agente ───────────────────────────────────────────────

    def _seleccionar_agente(self, mensaje: str, agente_id: str | None):
        """Agente explícito > match por área en el mensaje > primero disponible."""
        orq = self._get_orquestador()
        if orq is None:
            return None, None
        if agente_id and agente_id in orq.agentes:
            return agente_id, orq.agentes[agente_id]
        msg_lower = mensaje.lower()
        for k, ag in orq.agentes.items():
            if (ag.area or "").lower() in msg_lower:
                return k, ag
        if orq.agentes:
            return next(iter(orq.agentes.items()))
        return None, None

    # ── Ejecución de tareas ───────────────────────────────────────────────

    async def ejecutar_tarea(
        self, agente_id: str, tarea: str,
        datos_extra: str | None = None, archivo_id: str | None = None,
        user_id: str = "anonimo",
    ) -> dict:
        """
        Ejecuta realizar_tarea() en el agente especificado, emitiendo telemetría
        en tiempo real y persistiendo el resultado en SQLite.
        Lanza LookupError si el agente no existe (404 en el borde HTTP).
        """
        if not kill_switch.is_active():
            return {"error": "Kill switch activo."}
        orq = self._get_orquestador()
        if orq is None:
            return {"error": "Orquestador no inicializado. Verifica GEMINI_API_KEY en el .env."}
        if agente_id not in orq.agentes:
            raise LookupError(f"Agente '{agente_id}' no encontrado.")

        await self._broadcast({
            "tipo":      "agente_ejecutando",
            "agente_id": agente_id,
            "tarea":     tarea,
        })

        _t0 = time.monotonic()
        try:
            agente = orq.agentes[agente_id]
            # Resolver datos: archivo_id > datos_extra > tarea normal
            # (elif deliberado: un archivo_id que falla NO cae a datos_extra)
            datos_texto = None
            if archivo_id:
                datos_texto = _leer_upload_texto(archivo_id)
            elif datos_extra:
                datos_texto = datos_extra

            if datos_texto:
                resultado = await agente.realizar_tarea_con_datos(datos_texto)
            else:
                resultado = await agente.realizar_tarea(tarea)

            duracion_s = round(time.monotonic() - _t0, 3)

            if resultado is None:
                await self._broadcast({"tipo": "tarea_abortada", "agente_id": agente_id, "tarea": tarea})
                self._guardar_ejecucion(agente_id, orq, tarea, False, duracion_s,
                                        "Abortado por guardrails")
                self._auditar(user_id, agente_id, "tarea", tarea, "",
                              "abortado_guardrails", duracion_s, False,
                              contexto=f"archivo_id={archivo_id or '-'}",
                              guardrails=list(getattr(getattr(agente, "pipeline", None), "ultimo_veredicto", []) or []))
                return {"ok": False, "agente_id": agente_id,
                        "motivo": "Pipeline abortado por guardrails. Ve a Pipeline -> Feed de Errores para ver el detalle."}

            # Error de API (cuota, red, etc.) — distinto de un abort del pipeline
            if isinstance(resultado, dict) and resultado.get("_api_error"):
                msg = resultado.get("_api_msg", "Error de API")
                await self._broadcast({"tipo": "tarea_error", "agente_id": agente_id, "error": msg})
                self._guardar_ejecucion(agente_id, orq, tarea, False, duracion_s, msg)
                self._auditar(user_id, agente_id, "tarea", tarea, msg,
                              "error_api", duracion_s, False)
                return {"ok": False, "agente_id": agente_id, "motivo": msg}

            await self._broadcast({
                "tipo":       "tarea_completada",
                "agente_id":  agente_id,
                "tarea":      tarea,
                "resumen":    resultado.get("resumen", "")[:200],
                "duracion_s": duracion_s,
            })
            agente_nombre = orq.agentes[agente_id].nombre
            self._guardar_ejecucion(
                agente_id, orq, tarea, True, duracion_s,
                resultado.get("resumen", "")[:500] if resultado else "",
                kpis=resultado.get("kpis", {}) if resultado else {},
                archivo_id=archivo_id,
            )
            self._auditar(user_id, agente_id, "tarea", tarea,
                          resultado.get("resumen", "") if resultado else "",
                          "aprobado", duracion_s, True,
                          contexto=f"archivo_id={archivo_id or '-'}",
                          modelo=getattr(agente, "modelo", ""),
                          guardrails=list(getattr(getattr(agente, "pipeline", None), "ultimo_veredicto", []) or []))
            return {"ok": True, "agente_id": agente_id,
                    "agente_nombre": agente_nombre, "resultado": resultado}

        except Exception as exc:
            await self._broadcast({
                "tipo":      "tarea_error",
                "agente_id": agente_id,
                "error":     str(exc),
            })
            return {"ok": False, "agente_id": agente_id, "error": str(exc)}

    @staticmethod
    def _auditar(user_id, agente_id, tipo, prompt, respuesta, veredicto,
                 duracion_s, exitoso, contexto="", modelo="",
                 herramientas=None, contexto_hats="", guardrails=None) -> None:
        """Traza forense best-effort (ADR-0007/0014): nunca rompe la interacción."""
        from core.services.audit_service import registrar_interaccion
        registrar_interaccion(
            tipo=tipo, agente_id=agente_id, prompt=prompt, respuesta=respuesta,
            user_id=user_id, contexto=contexto, contexto_hats=contexto_hats, modelo=modelo,
            herramientas=herramientas or [], veredicto_guardrail=veredicto,
            guardrails=guardrails or [], duracion_s=duracion_s, exitoso=exitoso,
        )

    @staticmethod
    def _guardar_ejecucion(agente_id, orq, tarea, exitoso, duracion_s,
                           resumen, kpis=None, archivo_id=None) -> None:
        """Persistencia best-effort en SQLite (nunca rompe la respuesta)."""
        try:
            from core.database import guardar_ejecucion
            guardar_ejecucion(
                agente_id=agente_id, agente_nombre=orq.agentes[agente_id].nombre,
                tarea=tarea, exitoso=exitoso, duracion_s=duracion_s,
                resumen=resumen, kpis=kpis or {}, archivo_id=archivo_id,
            )
        except Exception:
            pass

    # ── Chat conversacional ───────────────────────────────────────────────

    async def chat(
        self, mensaje: str, agente_id: str | None = None,
        archivo_id: str | None = None, sesion_id: str = "default",
        user_id: str = "anonimo",
    ) -> dict:
        """Chat con tool-calling automático y fallback; timeout de 90 s."""
        if self._get_orquestador() is None:
            return {"error": "Orquestador no disponible.", "respuesta": None}

        agente_key, agente = self._seleccionar_agente(mensaje, agente_id)
        if agente is None:
            return {"error": "No hay agentes disponibles.", "respuesta": None}

        await self._broadcast({"tipo": "chat_procesando",
                               "agente_id": agente_key,
                               "agente_nombre": agente.nombre})
        _t0 = time.monotonic()
        herramientas_usadas: list[str] = []
        respuesta = None
        # ADR-0008: reintentos con backoff exponencial (2s, 4s) para absorber
        # latencias transitorias de red o de proveedores LLM pesados.
        MAX_INTENTOS = 3
        for intento in range(MAX_INTENTOS):
            try:
                respuesta, herramientas_usadas = await asyncio.wait_for(
                    agente.chat_con_herramientas(
                        mensaje,
                        sesion_id=sesion_id,
                        agente_id_clave=agente_key,
                        archivo_id=archivo_id,
                        user_id=user_id,
                    ),
                    timeout=90.0,
                )
                if herramientas_usadas:
                    await self._broadcast({
                        "tipo":         "herramientas_usadas",
                        "agente_id":    agente_key,
                        "herramientas": herramientas_usadas,
                    })
                break
            except asyncio.TimeoutError:
                if intento < MAX_INTENTOS - 1:
                    espera = 2.0 * (2 ** intento)
                    logger.warning("chat '%s': timeout de paso (90s), reintento %d/%d en %.0fs",
                                   agente.nombre, intento + 1, MAX_INTENTOS - 1, espera)
                    await asyncio.sleep(espera)
                else:
                    respuesta = "⏰ El agente tardó más de 90 segundos (3 intentos). Intenta de nuevo."
        await self._broadcast({"tipo": "chat_respuesta",
                               "agente_id": agente_key,
                               "agente_nombre": agente.nombre})

        logger.info("chat '%s': respondido", agente.nombre, extra={"agente": agente.nombre})
        self._auditar(user_id, agente_key, "chat", mensaje, respuesta,
                      "no_aplica", round(time.monotonic() - _t0, 3), True,
                      contexto=f"sesion={sesion_id} archivo_id={archivo_id or '-'}",
                      modelo=getattr(agente, "modelo", ""),
                      herramientas=herramientas_usadas,
                      contexto_hats=getattr(agente, "ultimo_contexto_hats", ""))
        return {"respuesta": respuesta, "agente_id": agente_key,
                "agente_nombre": agente.nombre, "agente_area": agente.area}

    async def chat_stream(
        self, mensaje: str, agente_id: str | None = None,
        archivo_id: str | None = None, sesion_id: str = "default",
        user_id: str = "anonimo",
    ) -> AsyncIterator[dict]:
        """
        Chat streaming como generador de eventos dict; el adaptador HTTP los
        serializa a SSE. Timeout por PASO (no por conversación completa):
        chat_con_herramientas_stream puede encadenar hasta MAX_PASOS=6 llamadas
        al modelo antes de la respuesta final, y un límite global cortaba
        conversaciones con varias herramientas que seguían avanzando.
        """
        if self._get_orquestador() is None:
            yield {"error": "Orquestador no disponible"}
            return

        agente_key, agente = self._seleccionar_agente(mensaje, agente_id)
        if agente is None:
            yield {"error": "No hay agentes disponibles"}
            return

        texto_completo = ""
        yield {"tipo": "inicio", "agente_nombre": agente.nombre,
               "agente_area": agente.area, "agente_id": agente_key}

        _t0 = time.monotonic()
        # ADR-0008: 90 s por paso — absorbe latencias de proveedores pesados
        # en tareas industriales complejas sin cortar conversaciones vivas.
        PASO_TIMEOUT_S = 90.0
        try:
            aiter = agente.chat_con_herramientas_stream(
                mensaje,
                sesion_id=sesion_id,
                agente_id_clave=agente_key,
                archivo_id=archivo_id,
                user_id=user_id,
            ).__aiter__()

            while True:
                try:
                    evento = await asyncio.wait_for(aiter.__anext__(), timeout=PASO_TIMEOUT_S)
                except StopAsyncIteration:
                    break
                if evento.get("tipo") == "chunk":
                    texto_completo += evento["chunk"]
                yield evento

        except asyncio.TimeoutError:
            yield {"tipo": "error",
                   "error": f"Tiempo de espera agotado ({int(PASO_TIMEOUT_S)}s) esperando un paso del modelo. Intenta de nuevo."}
        except Exception as exc:
            yield {"tipo": "error", "error": str(exc)}
        finally:
            self._auditar(user_id, agente_key, "chat_stream", mensaje,
                          texto_completo, "no_aplica",
                          round(time.monotonic() - _t0, 3), bool(texto_completo),
                          contexto=f"sesion={sesion_id} archivo_id={archivo_id or '-'}",
                          modelo=getattr(agente, "modelo", ""),
                          contexto_hats=getattr(agente, "ultimo_contexto_hats", ""))
            yield {"tipo": "fin", "texto_completo": texto_completo}

    # ── Control remoto (webhook ya autenticado) ───────────────────────────

    async def comando_remoto(self, comando: str) -> str:
        """Interpreta comandos de control remoto. La autenticación es del borde."""
        cmd       = comando.strip()
        cmd_lower = cmd.lower()

        if cmd_lower == "status":
            orq    = self._get_orquestador()
            n      = len(orq.agentes) if orq and hasattr(orq, "agentes") else 0
            activo = kill_switch.is_active()
            return (
                f"AgentDesk activo.\n"
                f"Agentes cargados: {n}\n"
                f"Kill switch: {'activo ✅' if activo else '⛔ desactivado'}"
            )

        if cmd_lower.startswith("reiniciar agente "):
            agente_id = cmd[len("Reiniciar Agente "):].strip()
            if not agente_id:
                return "Uso: Reiniciar Agente <id_del_agente>"
            bridge = self._get_bridge()
            if not bridge:
                return "Bridge no disponible — el orquestador no está en línea."
            await bridge.send(Command(tipo=RELOAD_CONFIG, payload={"agente_id": agente_id}))
            return f"Recarga de '{agente_id}' encolada correctamente."

        return (
            f"Comando no reconocido: '{cmd}'.\n\n"
            f"Comandos disponibles:\n{COMANDOS_REMOTOS_AYUDA}"
        )
