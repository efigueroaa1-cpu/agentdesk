import asyncio
import json
import logging
import os
from google import genai

from pydantic import ValidationError
from data.middleware import consultar_datos_seguros
from core.schemas import ReporteAgente, extraer_json_objeto
from core.pipeline import PipelineProcessor
from core.command_bridge import CommandBridge
import core.reporter as reporter
from core.orchestrator_chat_tools import AgentChatToolsMixin
from core.orchestrator_chat_tools_stream import AgentChatToolsStreamMixin
from core.orchestrator_tasks import AgentTasksMixin
from core.orchestrator_engine import OrquestadorEngineMixin
from core.orchestrator_registry import OrquestadorRegistryMixin
from core.orchestrator_bridge import OrquestadorBridgeMixin

logger = logging.getLogger(__name__)

_MODELO_FALLBACK      = "models/gemini-2.5-flash"
_TEMPERATURA_FALLBACK = 0.4


class AgentBase(AgentChatToolsMixin, AgentChatToolsStreamMixin, AgentTasksMixin):
    """
    Agente individual configurable por parámetros en config.json.

    Parámetros dinámicos (todos opcionales, con fallback):
      modelo      — modelo de Gemini
      temperatura — creatividad (0.0 preciso / 1.0 creativo)
      idioma      — directriz de idioma inyectada en el prompt
      prompt_base — instrucción de rol del agente
    """

    def __init__(self, config: dict, client: genai.Client, model_name_global: str):
        self.nombre      = config["nombre"]
        self.tipo_ia     = config["tipo_ia"]
        self.client      = client
        self._aplicar_config(config, model_name_global)
        self.pipeline    = PipelineProcessor(nombre_agente=self.nombre)

        logger.info(
            "Agente inicializado",
            extra={
                "agente":      self.nombre,
                "modelo":      self.modelo,
                "temperatura": self.temperatura,
                "idioma":      self.idioma,
            },
        )

    def _aplicar_config(self, config: dict, fallback_modelo: str = "") -> None:
        """Aplica (o re-aplica) parámetros dinámicos desde un dict de config."""
        self.modelo             = config.get("modelo",             fallback_modelo or _MODELO_FALLBACK)
        self.temperatura        = float(config.get("temperatura",  _TEMPERATURA_FALLBACK))
        self.prompt_base        = config.get("prompt_base",        "").strip()
        self.idioma             = config.get("idioma",             "español").strip()
        self.area               = config.get("area",               "General").strip().title()
        # Encadenamiento: ID del siguiente agente al que pasar el resultado
        self.siguiente_agente_id = config.get("siguiente_agente_id", None)
        # HATs (ADR-0009): capacidades componibles atachadas por config.
        self.harnesses = list(config.get("harnesses", []))
        # Ultimo contexto de HATs inyectado (ADR-0014): canal lateral de
        # solo lectura para que orchestrator_service audite el contexto
        # RECUPERADO, no solo el mensaje del usuario, sin cambiar la firma
        # de retorno de los metodos de chat.
        self.ultimo_contexto_hats = ""
        # Fase 19 (ADR-0017): mismo patron de canal lateral -- que proveedor
        # respondio REALMENTE (puede diferir de self.modelo si hubo
        # fallback) y cuantos tokens exactos/estimados consumio la ultima
        # llamada, para que orchestrator_service audite la cadena de
        # resiliencia sin cambiar la firma de retorno de los metodos de chat.
        self.ultimo_proveedor_llm = ""
        self.ultimo_tokens_llm: dict = {}

    def reload_config(self, config: dict) -> bool:
        """
        Actualiza los parámetros del agente en caliente con validación Pydantic.

        Flujo:
          1. Snapshot del estado actual (garantía de rollback).
          2. Construir el dict completo rellenando ausentes con valores actuales.
          3. Validar contra AgentConfig.
          4a. Fallo  → log de error + return False (rollback implícito: no se toca nada).
          4b. Éxito  → aplicar parámetros validados + log de diff + return True.

        Retorna True si el reload fue aplicado, False si fue rechazado.
        """
        from pydantic import ValidationError
        from core.schemas import AgentConfig

        # ── 1. Snapshot ────────────────────────────────────────────────────────
        snapshot = {
            "modelo":      self.modelo,
            "temperatura": self.temperatura,
            "prompt_base": self.prompt_base,
            "idioma":      self.idioma,
        }

        # ── 2. Construir config completa (fallos parciales usan el valor actual) ─
        config_candidato = {
            "id":          config.get("id",          ""),
            "nombre":      self.nombre,
            "tipo_ia":     self.tipo_ia,
            "area":        config.get("area",        self.area),
            "modelo":      config.get("modelo",      self.modelo),
            "temperatura": config.get("temperatura", self.temperatura),
            "idioma":      config.get("idioma",      self.idioma),
            "prompt_base": config.get("prompt_base", self.prompt_base),
        }

        # ── 3. Validación Pydantic ─────────────────────────────────────────────
        try:
            validado = AgentConfig.model_validate(config_candidato)
        except ValidationError as e:
            logger.error(
                "RELOAD_CONFIG rechazado para '%s' — validacion fallida. "
                "Configuracion anterior mantenida (rollback).",
                self.nombre,
                extra={
                    "agente":            self.nombre,
                    "config_rechazada":  config_candidato,
                    "errores_pydantic":  [err["msg"] for err in e.errors()],
                    "rollback_aplicado": True,
                },
            )
            return False

        # ── 4b. Aplicar parámetros validados ──────────────────────────────────
        self.modelo      = validado.modelo
        self.temperatura = validado.temperatura
        self.prompt_base = validado.prompt_base
        self.idioma      = validado.idioma

        logger.info(
            "RELOAD_CONFIG aplicado para '%s'.",
            self.nombre,
            extra={
                "agente":           self.nombre,
                "modelo_antes":     snapshot["modelo"],
                "modelo_despues":   self.modelo,
                "temp_antes":       snapshot["temperatura"],
                "temp_despues":     self.temperatura,
                "idioma_antes":     snapshot["idioma"],
                "idioma_despues":   self.idioma,
                "rollback_aplicado": False,
            },
        )
        return True

    async def _contexto_harnesses(self, mensaje: str, agente_id_clave: str,
                                   user_id: str = "anonimo") -> str:
        """Contexto extra best-effort de los HATs configurados (ADR-0009/0010)."""
        if not self.harnesses:
            self.ultimo_contexto_hats = ""
            return ""
        try:
            from core.services.harness_service import harness_service
            extra = await harness_service.aplicar_pre(
                self.harnesses, agente_id_clave or self.nombre, mensaje, user_id=user_id,
            )
            self.ultimo_contexto_hats = extra or ""
            return f"\n\n{extra}\n" if extra else ""
        except Exception as exc:
            self.ultimo_contexto_hats = ""
            logger.warning("HATs: contexto no aplicado para '%s' (%s)",
                           self.nombre, exc, extra={"agente": self.nombre})
            return ""

    async def _criticar_respuesta(self, mensaje: str, respuesta: str,
                                   agente_id_clave: str, user_id: str = "anonimo") -> str:
        """Post-hook best-effort de autocrítica (CritiqueHarness, ADR-0010)."""
        if not self.harnesses:
            return respuesta
        try:
            from core.services.harness_service import harness_service
            return await harness_service.aplicar_post(
                self.harnesses, agente_id_clave or self.nombre, respuesta,
                mensaje=mensaje, user_id=user_id, modelo=self.modelo,
            )
        except Exception as exc:
            logger.warning("HATs: autocritica no aplicada para '%s' (%s)",
                           self.nombre, exc, extra={"agente": self.nombre})
            return respuesta

    async def chat_libre(
        self,
        mensaje: str,
        contexto_archivo: str = "",
        sesion_id: str = "default",
        agente_id_clave: str = "",
        user_id: str = "anonimo",
    ) -> str:
        """
        Responde en modo conversacional libre con memoria persistente.
        La memoria guarda los últimos N mensajes en SQLite y los inyecta
        al prompt para que el agente mantenga el hilo de la conversación.
        """
        from core import memory as _mem

        aid = agente_id_clave or self.nombre

        # 1. Guardar el mensaje del usuario en memoria
        _mem.guardar_mensaje(aid, sesion_id, "usuario", mensaje)

        # 2. Recuperar contexto de la conversación anterior
        historial_ctx = _mem.get_contexto(aid, sesion_id, n_mensajes=8)

        # 3. Construir el prompt con memoria + contexto de archivo
        rol         = f"{self.prompt_base}\n\n" if self.prompt_base else ""
        archivo_ctx = (f"\n\nContenido del archivo adjunto:\n{contexto_archivo[:6000]}\n"
                       if contexto_archivo else "")
        memoria_ctx = f"\n\n{historial_ctx}\n" if historial_ctx else ""
        harness_ctx = await self._contexto_harnesses(mensaje, aid, user_id)

        prompt = (
            f"{rol}"
            f"Responde siempre en {self.idioma}. "
            f"Eres {self.nombre}, agente de área {self.area}. "
            f"Responde de forma clara, directa y coherente con el historial."
            f"{memoria_ctx}{harness_ctx}{archivo_ctx}\n\n"
            f"Usuario: {mensaje}"
        )

        # 4. Generar respuesta -- via la cadena de resiliencia (Fase 19,
        # ADR-0017): self.modelo se intenta primero (eleccion del agente
        # respetada), y si falla (429/503/timeout/red) la cadena salta
        # automaticamente al siguiente proveedor sano en vez de devolver un
        # mensaje pidiendole al usuario que reconfigure algo a mano. Solo
        # lanza si TODA la cadena, incluido el mock final, falla -- un bug
        # real, no un fallo de proveedor.
        from core.services.llm_service import llm_service
        from core.telemetry_otel import medir_paso
        try:
            with medir_paso("llm.generar", agente=self.nombre, modelo=self.modelo):
                resultado_llm = await llm_service.generar(
                    prompt, temperatura=self.temperatura, modelo_preferido=self.modelo,
                )
        except Exception as exc:
            logger.error("chat_libre '%s': cadena de resiliencia agotada (%s)",
                         self.nombre, exc, extra={"agente": self.nombre, "error_type": "chat_api"})
            return f"Error al procesar la solicitud: {exc}"

        respuesta = resultado_llm["texto"]
        self.ultimo_proveedor_llm = resultado_llm["proveedor"]
        self.ultimo_tokens_llm    = {
            "tokens_entrada": resultado_llm.get("tokens_entrada"),
            "tokens_salida":  resultado_llm.get("tokens_salida"),
            "tokens_total":   resultado_llm.get("tokens_total"),
            "tokens_exactos": resultado_llm.get("tokens_exactos", False),
        }

        # 5. Autocritica (CritiqueHarness, ADR-0010) + guardar en memoria
        respuesta = await self._criticar_respuesta(mensaje, respuesta, aid, user_id)
        _mem.guardar_mensaje(aid, sesion_id, "agente", respuesta)
        return respuesta

    async def chat_libre_stream(
        self,
        mensaje: str,
        contexto_archivo: str = "",
        sesion_id: str = "default",
        agente_id_clave: str = "",
        user_id: str = "anonimo",
    ):
        """
        Versión streaming de chat_libre.
        Devuelve chunks de texto conforme Groq los genera.
        Cada chunk es un string parcial de la respuesta.
        """
        from core.providers import generate_stream
        from core import memory as _mem

        aid = agente_id_clave or self.nombre
        _mem.guardar_mensaje(aid, sesion_id, "usuario", mensaje)

        historial_ctx = _mem.get_contexto(aid, sesion_id, n_mensajes=8)
        rol           = f"{self.prompt_base}\n\n" if self.prompt_base else ""
        archivo_ctx   = (f"\n\nContenido del archivo adjunto:\n{contexto_archivo[:6000]}\n"
                         if contexto_archivo else "")
        memoria_ctx   = f"\n\n{historial_ctx}\n" if historial_ctx else ""
        harness_ctx   = await self._contexto_harnesses(mensaje, aid, user_id)

        prompt = (
            f"{rol}"
            f"Responde siempre en {self.idioma}. "
            f"Eres {self.nombre}, agente de área {self.area}. "
            f"Responde de forma clara, directa y coherente con el historial."
            f"{memoria_ctx}{harness_ctx}{archivo_ctx}\n\n"
            f"Usuario: {mensaje}"
        )

        texto_completo = ""
        try:
            async for chunk in generate_stream(self.modelo, prompt, self.temperatura):
                texto_completo += chunk
                yield chunk
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "quota" in msg.lower():
                yield "⚠️ Cuota agotada. Configura Groq en Sistema → Proveedores IA."
            elif "503" in msg:
                yield "⚠️ Servicio saturado. Intenta de nuevo en unos segundos."
            else:
                yield f"⚠️ Error: {exc}"
            return

        # Guardar respuesta completa en memoria
        if texto_completo:
            _mem.guardar_mensaje(aid, sesion_id, "agente", texto_completo)

class Orquestador(OrquestadorEngineMixin, OrquestadorRegistryMixin, OrquestadorBridgeMixin):
    """
    Gestiona los agentes y escucha comandos del CommandBridge.

    El CommandBridge es opcional: si no se pasa, el sistema funciona
    igual que antes sin soporte para recarga dinámica.
    """

    def __init__(
        self,
        config_path: str,
        client: genai.Client,
        model_name_global: str,
        bridge: CommandBridge | None = None,
    ):
        self._config_path       = config_path
        self._model_name_global = model_name_global
        self._bridge            = bridge
        self._client            = client

        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.agentes = {
            a["id"]: AgentBase(a, client, model_name_global)
            for a in self.config["agents"]
        }

        # Sandbox Zero-Trust (Fase 7): cualquier subproceso disparado por un agente
        # pasa por este runner (shell prohibida, entorno minimo sin API keys,
        # limites de tiempo/memoria). Ver core/services/sandbox_service.py.
        from core.services.sandbox_service import SubprocessRunner
        self.sandbox = SubprocessRunner()

        os.makedirs("reportes", exist_ok=True)
