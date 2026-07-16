import asyncio
import json
import logging
import os
from google import genai

from pydantic import ValidationError
from data.middleware import consultar_datos_seguros
from core.schemas import ReporteAgente
from core.pipeline import PipelineProcessor
from core.command_bridge import CommandBridge, Command, RELOAD_CONFIG, CREAR_AGENTE, ELIMINAR_AGENTE, ACTUALIZAR_AGENTE, RELOAD_FINANZAS
import core.reporter as reporter

logger = logging.getLogger(__name__)

_MODELO_FALLBACK      = "models/gemini-2.5-flash"
_TEMPERATURA_FALLBACK = 0.4


class AgentBase:
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

    async def chat_con_herramientas(
        self,
        mensaje: str,
        sesion_id:       str = "default",
        agente_id_clave: str = "",
        archivo_id:      str | None = None,
        user_id:         str = "anonimo",
    ) -> tuple[str, list[str]]:
        """
        Chat con Tool Calling — el agente decide solo qué herramientas usar.
        Retorna (respuesta_final, herramientas_usadas).
        Soporta Gemini (nativo), Groq, OpenAI y DeepSeek.
        """
        from core.tools import TOOLS_SCHEMA, ejecutar_herramienta
        from core.providers import parse_model_id
        from core import memory as _mem

        proveedor, modelo_real = parse_model_id(self.modelo)

        # Anthropic no tiene tool calling en este flujo — fallback
        if proveedor not in ("groq", "openai", "deepseek", "gemini"):
            respuesta = await self.chat_libre(mensaje, sesion_id=sesion_id,
                                              agente_id_clave=agente_id_clave,
                                              user_id=user_id)
            return respuesta, []

        # Fase 19 (ADR-0017): el loop de tool-calling nativo de abajo habla
        # DIRECTO con el SDK del proveedor (necesita su protocolo propio de
        # tool_calls, no el generar() de texto plano de llm_service) — pero
        # comparte el MISMO circuito. Si ya esta abierto por fallos
        # recientes, no tiene sentido intentarlo: saltar directo a
        # chat_libre, que SI recorre la cadena de resiliencia completa.
        from core.services.llm_service import llm_service
        if not llm_service.disponible(proveedor):
            logger.warning(
                "chat_con_herramientas '%s': circuito de '%s' abierto, saltando a chat_libre",
                self.nombre, proveedor, extra={"agente": self.nombre},
            )
            respuesta = await self.chat_libre(mensaje, sesion_id=sesion_id,
                                              agente_id_clave=agente_id_clave,
                                              user_id=user_id)
            return respuesta, []

        aid = agente_id_clave or self.nombre
        _mem.guardar_mensaje(aid, sesion_id, "usuario", mensaje)

        async def _cerrar(texto: str) -> tuple[str, list[str]]:
            """Autocritica (CritiqueHarness, ADR-0010) + guardar en memoria."""
            llm_service.registrar_exito(proveedor)   # ADR-0017: circuito compartido
            self.ultimo_proveedor_llm = proveedor
            texto = await self._criticar_respuesta(mensaje, texto, aid, user_id)
            _mem.guardar_mensaje(aid, sesion_id, "agente", texto)
            return texto, herramientas_usadas

        historial_ctx = _mem.get_contexto(aid, sesion_id, n_mensajes=6)
        rol           = f"{self.prompt_base}\n\n" if self.prompt_base else ""
        memoria_ctx   = f"\n\n{historial_ctx}\n" if historial_ctx else ""
        harness_ctx   = await self._contexto_harnesses(mensaje, aid, user_id)

        archivo_hint = (
            f"\nEl usuario ha adjuntado el archivo con ID '{archivo_id}'. "
            f"Usa leer_archivo(archivo_id='{archivo_id}') para acceder a él."
            if archivo_id else
            "\nSi necesitas datos de un archivo, usa listar_archivos() primero para ver qué hay disponible."
        )
        system_prompt = (
            f"{rol}"
            f"Eres {self.nombre}, agente de área {self.area}. "
            f"Responde siempre en {self.idioma}.\n\n"
            f"REGLAS ESTRICTAS sobre herramientas:\n"
            f"1. NUNCA menciones archivos que no hayas leído con leer_archivo() o listar_archivos().\n"
            f"2. NUNCA inventes nombres de archivos, datos o valores numéricos.\n"
            f"3. Si el usuario menciona un archivo o presupuesto, PRIMERO llama listar_archivos() para ver qué existe realmente.\n"
            f"4. USA calcular() para TODA operación matemática, nunca calcules mentalmente.\n"
            f"5. Si no tienes un dato, di 'No tengo ese dato, ¿puedes proporcionarlo?' en lugar de inventarlo.\n"
            f"{archivo_hint}"
            f"{memoria_ctx}{harness_ctx}"
        )

        herramientas_usadas = []
        MAX_PASOS = 6

        try:
            # ── Gemini: function calling nativo ───────────────────────────────
            if proveedor == "gemini":
                from google import genai as _genai
                from google.genai import types as _gt

                client = _genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))

                # Convertir TOOLS_SCHEMA (formato OpenAI) a FunctionDeclaration de Gemini
                gemini_funcs = [
                    _gt.FunctionDeclaration(
                        name=t["function"]["name"],
                        description=t["function"]["description"],
                        parameters=t["function"].get("parameters",
                                                     {"type": "object", "properties": {}}),
                    )
                    for t in TOOLS_SCHEMA
                ]
                gemini_tools = [_gt.Tool(function_declarations=gemini_funcs)]
                gen_cfg = _gt.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=gemini_tools,
                    temperature=self.temperatura,
                )

                # Historial como contexto inicial
                contents: list = []
                if historial_ctx:
                    contents.append(_gt.Content(role="user",
                                                parts=[_gt.Part(text=historial_ctx)]))
                    contents.append(_gt.Content(role="model",
                                                parts=[_gt.Part(text="Entendido.")]))
                contents.append(_gt.Content(role="user",
                                            parts=[_gt.Part(text=mensaje)]))

                for _ in range(MAX_PASOS):
                    response  = await client.aio.models.generate_content(
                        model=modelo_real, contents=contents, config=gen_cfg,
                    )
                    candidate = response.candidates[0]
                    parts     = candidate.content.parts if candidate.content else []

                    fn_calls   = [p.function_call for p in parts
                                  if getattr(p, "function_call", None)]
                    text_parts = [p.text for p in parts
                                  if getattr(p, "text", None)]

                    if not fn_calls:
                        respuesta = "".join(text_parts).strip()
                        return await _cerrar(respuesta)

                    # Añadir respuesta del modelo al hilo
                    contents.append(candidate.content)

                    # Ejecutar herramientas y devolver resultados
                    tool_parts = []
                    for fc in fn_calls:
                        nombre_tool = fc.name
                        args        = dict(fc.args) if fc.args else {}
                        herramientas_usadas.append(nombre_tool)
                        logger.info("Agente '%s' usa herramienta (Gemini): %s(%s)",
                                    self.nombre, nombre_tool, args,
                                    extra={"agente": self.nombre})
                        resultado = await ejecutar_herramienta(
                            nombre_tool, args, agente_id_clave=aid, user_id=user_id,
                        )
                        tool_parts.append(_gt.Part(
                            function_response=_gt.FunctionResponse(
                                name=nombre_tool,
                                response={"result": str(resultado)[:4000]},
                            )
                        ))
                    contents.append(_gt.Content(role="user", parts=tool_parts))

                # Excedió max_pasos — pedir respuesta final sin tools
                contents.append(_gt.Content(role="user",
                    parts=[_gt.Part(text="Responde con los datos que tienes hasta ahora.")]))
                response  = await client.aio.models.generate_content(
                    model=modelo_real, contents=contents,
                    config=_gt.GenerateContentConfig(temperature=self.temperatura),
                )
                respuesta = (response.text or "").strip()
                return await _cerrar(respuesta)

            # ── Groq / OpenAI / DeepSeek (API compatible OpenAI) ─────────────
            if proveedor == "groq":
                from groq import AsyncGroq
                client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))
            elif proveedor == "deepseek":
                from openai import AsyncOpenAI
                client = AsyncOpenAI(
                    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                    base_url="https://api.deepseek.com",
                )
            else:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": mensaje},
            ]

            for _ in range(MAX_PASOS):
                response = await client.chat.completions.create(
                    model=modelo_real, messages=messages, tools=TOOLS_SCHEMA,
                    tool_choice="auto", temperature=self.temperatura, max_tokens=4096,
                )
                msg    = response.choices[0].message
                finish = response.choices[0].finish_reason

                if finish == "stop" or not msg.tool_calls:
                    respuesta = msg.content or ""
                    return await _cerrar(respuesta)

                messages.append({"role": "assistant", "content": msg.content or "",
                                  "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})

                for tc in msg.tool_calls:
                    nombre_tool = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                    herramientas_usadas.append(nombre_tool)
                    logger.info("Agente '%s' usa herramienta: %s(%s)",
                                self.nombre, nombre_tool, args,
                                extra={"agente": self.nombre})
                    resultado = await ejecutar_herramienta(
                        nombre_tool, args, agente_id_clave=aid, user_id=user_id,
                    )
                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      str(resultado)[:4000],
                    })

            # Excedió max_pasos
            messages.append({"role": "user",
                              "content": "Responde con los datos que tienes hasta ahora."})
            response  = await client.chat.completions.create(
                model=modelo_real, messages=messages,
                temperature=self.temperatura, max_tokens=2048,
            )
            respuesta = response.choices[0].message.content or ""
            return await _cerrar(respuesta)

        except Exception as exc:
            # ADR-0017: el fallo del loop nativo TAMBIEN cuenta para el
            # circuito compartido -- no solo los fallos vistos por generar().
            # Sin esto, un proveedor que solo falla en tool-calling (p.ej.
            # un endpoint de function-calling caido) nunca abriria su
            # circuito, y cada mensaje pagaria el mismo timeout antes de
            # caer a chat_libre en vez de saltarselo la proxima vez.
            llm_service.registrar_fallo(proveedor, f"{type(exc).__name__}: {str(exc)[:120]}")
            logger.error("chat_con_herramientas '%s': %s", self.nombre, exc,
                         extra={"agente": self.nombre})
            respuesta = await self.chat_libre(mensaje, sesion_id=sesion_id,
                                              agente_id_clave=agente_id_clave,
                                              user_id=user_id)
            return respuesta, []

    async def chat_con_herramientas_stream(
        self,
        mensaje: str,
        sesion_id:       str = "default",
        agente_id_clave: str = "",
        archivo_id:      str | None = None,
        user_id:         str = "anonimo",
    ):
        """
        Streaming con Tool Calling en dos fases:
          Fase 1 (tools)    — loop no-streaming: emite eventos tool_call / tool_result.
          Fase 2 (respuesta)— streaming real: emite eventos chunk.

        Yield: dict con clave 'tipo' ∈ {tool_call, tool_result, chunk, error}.

        Proveedores soportados: gemini, groq, openai, deepseek.
        Fallback a chat_libre_stream para proveedores sin tool calling.
        """
        from core.tools import TOOLS_SCHEMA, ejecutar_herramienta
        from core.providers import parse_model_id, generate_stream
        from core import memory as _mem

        proveedor, modelo_real = parse_model_id(self.modelo)

        # Proveedores sin tool calling → streaming directo sin tools
        if proveedor not in ("groq", "openai", "deepseek", "gemini"):
            async for chunk in self.chat_libre_stream(mensaje, "", sesion_id, agente_id_clave,
                                                       user_id=user_id):
                yield {"tipo": "chunk", "chunk": chunk}
            return

        aid = agente_id_clave or self.nombre
        _mem.guardar_mensaje(aid, sesion_id, "usuario", mensaje)

        historial_ctx = _mem.get_contexto(aid, sesion_id, n_mensajes=6)
        rol           = f"{self.prompt_base}\n\n" if self.prompt_base else ""
        memoria_ctx   = f"\n\n{historial_ctx}\n" if historial_ctx else ""
        harness_ctx   = await self._contexto_harnesses(mensaje, aid, user_id)

        archivo_hint = (
            f"\nEl usuario ha adjuntado el archivo con ID '{archivo_id}'. "
            f"Usa leer_archivo(archivo_id='{archivo_id}') para acceder a él."
            if archivo_id else
            "\nSi necesitas datos de un archivo, usa listar_archivos() primero."
        )
        system_prompt = (
            f"{rol}"
            f"Eres {self.nombre}, agente de área {self.area}. "
            f"Responde siempre en {self.idioma}.\n\n"
            f"REGLAS SOBRE HERRAMIENTAS:\n"
            f"1. Para indicadores del Banco Central (UF, dólar, IPC) SIEMPRE usa consultar_indicadores_chile().\n"
            f"2. NUNCA inventes valores numéricos — usa las herramientas disponibles.\n"
            f"3. Para archivos usa leer_archivo() o listar_archivos().\n"
            f"4. Para cálculos usa calcular().\n"
            f"{archivo_hint}"
            f"{memoria_ctx}{harness_ctx}"
        )

        herramientas_usadas: list[str] = []
        resultados_tools:    list[str] = []
        MAX_PASOS = 6

        try:
            # ── FASE 1: Tool calling (no streaming) ───────────────────────────
            if proveedor == "gemini":
                from google import genai as _genai
                from google.genai import types as _gt

                client = _genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
                gemini_funcs = [
                    _gt.FunctionDeclaration(
                        name=t["function"]["name"],
                        description=t["function"]["description"],
                        parameters=t["function"].get("parameters",
                                                     {"type": "object", "properties": {}}),
                    )
                    for t in TOOLS_SCHEMA
                ]
                gen_cfg_tools = _gt.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=[_gt.Tool(function_declarations=gemini_funcs)],
                    temperature=self.temperatura,
                )

                contents: list = []
                if historial_ctx:
                    contents.append(_gt.Content(role="user",
                                                parts=[_gt.Part(text=historial_ctx)]))
                    contents.append(_gt.Content(role="model",
                                                parts=[_gt.Part(text="Entendido.")]))
                contents.append(_gt.Content(role="user",
                                            parts=[_gt.Part(text=mensaje)]))

                for _ in range(MAX_PASOS):
                    resp      = await client.aio.models.generate_content(
                        model=modelo_real, contents=contents, config=gen_cfg_tools,
                    )
                    candidate = resp.candidates[0]
                    parts     = candidate.content.parts if candidate.content else []
                    fn_calls  = [p.function_call for p in parts
                                 if getattr(p, "function_call", None)]

                    if not fn_calls:
                        break   # modelo terminó el loop de tools

                    contents.append(candidate.content)
                    tool_parts = []
                    for fc in fn_calls:
                        nombre_tool = fc.name
                        args        = dict(fc.args) if fc.args else {}
                        herramientas_usadas.append(nombre_tool)

                        yield {"tipo": "tool_call",
                               "herramienta": nombre_tool,
                               "args": {k: str(v)[:120] for k, v in args.items()}}

                        resultado = await ejecutar_herramienta(
                            nombre_tool, args, agente_id_clave=aid, user_id=user_id,
                        )
                        res_str   = str(resultado)
                        resultados_tools.append(f"[{nombre_tool}]\n{res_str[:800]}")

                        yield {"tipo": "tool_result",
                               "herramienta": nombre_tool,
                               "preview": res_str[:200]}

                        tool_parts.append(_gt.Part(
                            function_response=_gt.FunctionResponse(
                                name=nombre_tool,
                                response={"result": res_str[:4000]},
                            )
                        ))
                    contents.append(_gt.Content(role="user", parts=tool_parts))

                # ── FASE 2: Respuesta streaming con contexto de tools ────────
                ctx_tools = (
                    "\n\nDatos obtenidos de herramientas:\n" +
                    "\n\n".join(resultados_tools)
                    if resultados_tools else ""
                )
                prompt_final = (
                    f"{system_prompt}{ctx_tools}\n\n"
                    f"Usuario: {mensaje}\n"
                    f"Responde usando los datos anteriores. No menciones que usaste herramientas."
                )
                texto_completo = ""
                async for chunk in generate_stream(self.modelo, prompt_final, self.temperatura):
                    texto_completo += chunk
                    yield {"tipo": "chunk", "chunk": chunk}
                _mem.guardar_mensaje(aid, sesion_id, "agente", texto_completo)

            else:
                # ── Groq / OpenAI / DeepSeek ──────────────────────────────────
                if proveedor == "groq":
                    from groq import AsyncGroq
                    client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))
                elif proveedor == "deepseek":
                    from openai import AsyncOpenAI
                    client = AsyncOpenAI(
                        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                        base_url="https://api.deepseek.com",
                    )
                else:
                    from openai import AsyncOpenAI
                    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

                messages: list = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": mensaje},
                ]

                # Fase 1: tool calling (no streaming)
                for _ in range(MAX_PASOS):
                    resp   = await client.chat.completions.create(
                        model=modelo_real, messages=messages, tools=TOOLS_SCHEMA,
                        tool_choice="auto", temperature=self.temperatura, max_tokens=4096,
                    )
                    msg    = resp.choices[0].message
                    finish = resp.choices[0].finish_reason

                    if finish == "stop" or not msg.tool_calls:
                        break

                    messages.append({
                        "role":       "assistant",
                        "content":    msg.content or "",
                        "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                    })

                    for tc in msg.tool_calls:
                        nombre_tool = tc.function.name
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                            if not isinstance(args, dict):
                                args = {}
                        except Exception:
                            args = {}
                        herramientas_usadas.append(nombre_tool)

                        yield {"tipo": "tool_call",
                               "herramienta": nombre_tool,
                               "args": {k: str(v)[:120] for k, v in args.items()}}

                        resultado = await ejecutar_herramienta(
                            nombre_tool, args, agente_id_clave=aid, user_id=user_id,
                        )
                        res_str   = str(resultado)
                        resultados_tools.append(f"[{nombre_tool}]\n{res_str[:800]}")

                        yield {"tipo": "tool_result",
                               "herramienta": nombre_tool,
                               "preview": res_str[:200]}

                        messages.append({
                            "role":         "tool",
                            "tool_call_id": tc.id,
                            "content":      res_str[:4000],
                        })

                # Fase 2: streaming real de la respuesta final
                stream = await client.chat.completions.create(
                    model=modelo_real,
                    messages=messages,
                    temperature=self.temperatura,
                    max_tokens=2048,
                    stream=True,
                )
                texto_completo = ""
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        texto_completo += delta
                        yield {"tipo": "chunk", "chunk": delta}
                _mem.guardar_mensaje(aid, sesion_id, "agente", texto_completo)

        except Exception as exc:
            logger.error("chat_con_herramientas_stream '%s': %s", self.nombre, exc,
                         extra={"agente": self.nombre})
            yield {"tipo": "error", "error": str(exc)}

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

    async def realizar_tarea_con_datos(self, datos_texto: str) -> dict | None:
        """Analiza texto externo (CSV, Excel exportado, etc.) con el agente."""
        import re as _re
        # Limpiar artefactos de Excel antes de enviar al LLM
        limpio = datos_texto
        limpio = _re.sub(r"#[¡!]?DIV/0[!]?", "N/D", limpio)
        limpio = _re.sub(r"#[A-Z/!¡]+", "N/D", limpio)
        limpio = limpio[:16_000]
        return await self.realizar_tarea("analisis_externo", _datos_override=limpio)

    async def realizar_tarea(self, tarea: str, _datos_override: str | None = None) -> dict | None:
        datos    = _datos_override if _datos_override is not None else consultar_datos_seguros(f"LEER {tarea}")
        es_externo = isinstance(datos, str) and tarea in ("analisis_externo", "custom") or \
                     (isinstance(datos, dict) and datos.get("_es_texto_externo"))

        rol = f"{self.prompt_base}\n\n" if self.prompt_base else ""

        REGLA_IDIOMA = (
            "REGLA ABSOLUTA DE IDIOMA: Responde TODO en español. "
            "Los nombres de KPIs, columnas de tabla, títulos, resumen y evidencia "
            "deben estar en español. NUNCA uses inglés. "
            "Ejemplo correcto: 'Presupuesto Total', 'Monto Gastado', 'Porcentaje Ejecutado'. "
            "Ejemplo INCORRECTO: 'Total Budget', 'Amount Spent', 'Percentage'. "
        )

        if es_externo:
            datos_str = datos if isinstance(datos, str) else datos.get("_corpus", "")
            instruccion = (
                f"{rol}"
                f"{REGLA_IDIOMA}\n\n"
                "Eres un analista experto. Analiza el siguiente documento y extrae en ESPAÑOL:\n"
                "1) Un resumen ejecutivo claro y detallado en español.\n"
                "2) Los KPIs más importantes: totales, subtotales, porcentajes, variaciones (nombres en español).\n"
                "3) Una tabla con las partidas principales y sus valores (encabezados en español).\n"
                "4) Evidencia: para cada KPI, cita el valor exacto del documento.\n\n"
                f"DOCUMENTO:\n{datos_str}\n\n"
                "Responde ÚNICAMENTE en JSON válido. Todos los textos en español:\n"
                '{"resumen": "texto en español...", '
                '"kpis": {"Nombre KPI en Español": "valor"}, '
                '"tabla": [["Partida","Presupuesto","Gastado","Restante"], ["valor1","valor2","valor3","valor4"]], '
                '"evidencia": {"Nombre KPI en Español": "cita exacta del documento"}}'
            )
        else:
            instruccion = (
                f"{rol}"
                f"{REGLA_IDIOMA}\n\n"
                f"Analiza: {datos}. "
                "Responde ÚNICAMENTE en JSON válido. Todos los textos en español. "
                "RESTRICCION: en 'evidencia' cita el valor EXACTO de los datos originales. "
                'Estructura: {"resumen": "texto en español", '
                '"kpis": {"Nombre KPI en español": "valor"}, '
                '"tabla": [["Columna1","Columna2"], ["valor1","valor2"]], '
                '"evidencia": {"Nombre KPI en español": "fuente exacta del dato"}}'
            )

        raw_data = datos if isinstance(datos, dict) else {"_corpus": str(datos), "_es_texto_externo": True}

        # ── Bucle de auto-corrección: hasta 3 intentos ────────────────────────
        instruccion_actual = instruccion
        MAX_INTENTOS = 3

        for intento in range(1, MAX_INTENTOS + 1):
            # Llamar al modelo de IA -- via la cadena de resiliencia (Fase
            # 19, ADR-0017). Antes: un 429/503 del proveedor configurado
            # devolvia un _api_error pidiendole al usuario que reconfigure
            # otro proveedor A MANO. Ahora la cadena salta automaticamente
            # al siguiente proveedor sano; solo queda _api_error si TODA la
            # cadena, incluido el mock final, falla -- un bug real.
            from core.services.llm_service import llm_service
            try:
                resultado_llm = await llm_service.generar(
                    instruccion_actual, temperatura=self.temperatura,
                    modelo_preferido=self.modelo,
                )
            except Exception as exc_rt:
                return {"_api_error": True, "_api_msg": f"Error de API: {str(exc_rt)[:120]}"}

            respuesta_raw = resultado_llm["texto"]
            self.ultimo_proveedor_llm = resultado_llm["proveedor"]
            self.ultimo_tokens_llm    = {
                "tokens_entrada": resultado_llm.get("tokens_entrada"),
                "tokens_salida":  resultado_llm.get("tokens_salida"),
                "tokens_total":   resultado_llm.get("tokens_total"),
                "tokens_exactos": resultado_llm.get("tokens_exactos", False),
            }

            texto_limpio = respuesta_raw.replace("```json", "").replace("```", "").strip()

            # Parsear JSON
            try:
                raw = json.loads(texto_limpio)
            except json.JSONDecodeError as e:
                if intento < MAX_INTENTOS:
                    logger.warning("Agente '%s' intento %d: JSON inválido, reintentando", self.nombre, intento)
                    instruccion_actual = (
                        instruccion + f"\n\nCORRECCIÓN NECESARIA (intento {intento}/{MAX_INTENTOS}): "
                        f"Tu respuesta anterior no era JSON válido: {e}. "
                        "Responde ÚNICAMENTE con JSON válido, sin texto adicional."
                    )
                    continue
                logger.error("Agente '%s' — JSON inválido tras %d intentos", self.nombre, MAX_INTENTOS,
                             extra={"agente": self.nombre, "error_type": "json_decode"})
                return None

            # Validar schema
            try:
                reporte = ReporteAgente.model_validate(raw)
            except ValidationError as e:
                if intento < MAX_INTENTOS:
                    logger.warning("Agente '%s' intento %d: schema inválido, corrigiendo", self.nombre, intento)
                    campos_faltantes = [err["loc"][0] for err in e.errors() if err.get("loc")]
                    instruccion_actual = (
                        instruccion + f"\n\nCORRECCIÓN (intento {intento}/{MAX_INTENTOS}): "
                        f"El JSON no cumple el schema requerido. Campos con error: {campos_faltantes}. "
                        "Asegúrate de incluir: resumen (string), kpis (dict no vacío), "
                        "tabla (lista con encabezados), evidencia (dict con fuentes)."
                    )
                    continue
                return None

            # Ejecutar pipeline con auto-corrección
            resultado = await self.pipeline.procesar_con_razon(
                raw_data=raw_data,
                respuesta_texto=texto_limpio,
                reporte=reporte.model_dump(),
            )

            # Si el pipeline rechaza, construir prompt de corrección
            if isinstance(resultado, dict) and resultado.get("_abortado"):
                guardrail = resultado.get("_guardrail", "Pipeline")
                razon     = resultado.get("_razon", "Error de validación")

                if intento < MAX_INTENTOS:
                    logger.warning("Agente '%s' intento %d: %s rechazó — autocorrigiendo",
                                   self.nombre, intento, guardrail,
                                   extra={"agente": self.nombre, "guardrail": guardrail})
                    instruccion_actual = (
                        instruccion + f"\n\nCORRECCIÓN AUTOMÁTICA (intento {intento}/{MAX_INTENTOS}): "
                        f"El guardrail '{guardrail}' rechazó tu respuesta.\n"
                        f"Razón exacta: {razon}\n"
                        "Corrige estos problemas específicos y genera una nueva respuesta JSON."
                    )
                    continue
                else:
                    logger.error("Agente '%s' — pipeline abortó tras %d intentos de corrección",
                                 self.nombre, MAX_INTENTOS,
                                 extra={"agente": self.nombre, "error_type": "pipeline_abort",
                                        "status": "abortado", "motivo": razon})
                    return None

            # Pipeline pasó correctamente
            if resultado is not None:
                if intento > 1:
                    logger.info("Agente '%s' — tarea completada tras %d intentos de auto-corrección",
                                self.nombre, intento,
                                extra={"agente": self.nombre, "intentos": intento, "status": "ok_corregido"})
                else:
                    logger.info("Agente '%s' — tarea completada",
                                self.nombre,
                                extra={"agente": self.nombre, "modelo": self.modelo, "status": "ok"})
                reporter.guardar_reporte(self.nombre, resultado)
                try:
                    reporter.guardar_reporte_pdf(self.nombre, resultado)
                except Exception:
                    logger.exception(
                        "No se pudo generar el PDF del reporte (se conserva el .md)",
                        extra={"agente": self.nombre},
                    )
                return resultado

        return None

    async def realizar_tarea_encadenada(
        self,
        tarea: str,
        orquestador: "Orquestador",
        profundidad: int = 0,
        max_profundidad: int = 5,
    ) -> dict | None:
        """
        Ejecuta la tarea y, si el agente tiene `siguiente_agente_id` configurado,
        pasa el resultado como contexto enriquecido al siguiente agente.

        Protección anti-bucle: limita la cadena a `max_profundidad` saltos.
        El resumen del agente actual se inyecta al prompt del siguiente.
        """
        resultado = await self.realizar_tarea(tarea)

        if resultado is None or not self.siguiente_agente_id:
            return resultado

        if profundidad >= max_profundidad:
            logger.warning(
                "Cadena de agentes cortada: profundidad maxima (%d) alcanzada.",
                max_profundidad,
                extra={"agente": self.nombre, "siguiente": self.siguiente_agente_id},
            )
            return resultado

        siguiente = orquestador.agentes.get(self.siguiente_agente_id)
        if siguiente is None:
            logger.error(
                "Encadenamiento fallido: agente '%s' no encontrado.",
                self.siguiente_agente_id,
                extra={"agente_origen": self.nombre},
            )
            return resultado

        # Enriquecer el contexto: el resultado actual alimenta al siguiente
        resumen_previo = resultado.get("resumen", "")
        tarea_enriquecida = (
            f"{tarea}\n\n"
            f"CONTEXTO DEL AGENTE PREVIO ({self.nombre}):\n{resumen_previo}"
        )

        logger.info(
            "Encadenando '%s' -> '%s' (profundidad %d).",
            self.nombre, siguiente.nombre, profundidad + 1,
            extra={"cadena": f"{self.nombre}->{siguiente.nombre}"},
        )

        return await siguiente.realizar_tarea_encadenada(
            tarea_enriquecida, orquestador,
            profundidad=profundidad + 1,
            max_profundidad=max_profundidad,
        )


class Orquestador:
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

    # ── Recarga dinámica ───────────────────────────────────────────────────────

    def reload_agente(self, agente_id: str | None) -> list[str]:
        """
        Re-lee config.json y actualiza en caliente los parámetros del agente.

        agente_id=None → recarga todos los agentes.
        Retorna la lista de IDs que fueron actualizados.
        """
        from core.config_loader import load_config

        nuevo_cfg = load_config(self._config_path)
        self.config = nuevo_cfg                             # actualiza config en memoria

        actualizados: list[str] = []

        for ag_cfg in nuevo_cfg["agents"]:
            aid = ag_cfg["id"]
            if agente_id is not None and aid != agente_id:
                continue
            if aid in self.agentes:
                if self.agentes[aid].reload_config(ag_cfg):   # True = validado y aplicado
                    actualizados.append(aid)
                # False = validación fallida → rollback implícito, ya logueado
            else:
                logger.warning("RELOAD_CONFIG: agente_id '%s' no existe en el orquestador.", aid)

        return actualizados

    # ── Registro de nuevos agentes ────────────────────────────────────────────

    async def crear_nuevo_agente(self, data: dict) -> bool:
        """
        Registra un nuevo agente en el sistema.

        Flujo:
          1. Genera un agente_id único a partir del nombre.
          2. Valida el dict completo con AgentConfig (Pydantic).
          3. Crea el AgentBase y lo añade al registry en memoria.
          4. Persiste el nuevo agente en config.json.
          5. Emite un evento de auditoría en el log JSON.

        Retorna True si el agente fue creado, False si la validación falló.
        """
        import re
        from pydantic import ValidationError
        from core.schemas import AgentConfig

        nombre = data.get("nombre", "").strip()
        if not nombre:
            logger.error("CREAR_AGENTE rechazado: 'nombre' es obligatorio.")
            return False

        # Generar ID único: agente_<slug>_<n>
        slug       = re.sub(r"[^a-z0-9]+", "_", nombre.lower()).strip("_")
        agente_id  = f"agente_{slug}_{len(self.agentes) + 1:02d}"

        if agente_id in self.agentes:
            logger.error(
                "CREAR_AGENTE rechazado: agente_id '%s' ya existe.", agente_id,
                extra={"agente_id": agente_id},
            )
            return False

        config_candidato = {
            "id":          agente_id,
            "nombre":      nombre,
            "tipo_ia":     data.get("tipo_ia",     "general"),
            "area":        data.get("area",        "General"),   # campo obligatorio
            "modelo":      data.get("modelo",      self._model_name_global),
            "temperatura": data.get("temperatura", _TEMPERATURA_FALLBACK),
            "idioma":      data.get("idioma",      "español"),
            "prompt_base": data.get("prompt_base", ""),
        }

        # Validación Pydantic
        try:
            AgentConfig.model_validate(config_candidato)
        except ValidationError as e:
            logger.error(
                "CREAR_AGENTE rechazado: validación fallida para '%s'.",
                nombre,
                extra={
                    "nombre":          nombre,
                    "errores_pydantic": [err["msg"] for err in e.errors()],
                },
            )
            return False

        # Crear AgentBase y registrar
        nuevo = AgentBase(config_candidato, self._client, self._model_name_global)
        self.agentes[agente_id]       = nuevo
        self.config["agents"].append(config_candidato)

        # Persistencia en config.json
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

        # Evento de auditoría
        logger.info(
            "Nuevo agente registrado en el sistema.",
            extra={
                "evento":      "AGENTE_CREADO",
                "agente_id":   agente_id,
                "nombre":      nombre,
                "tipo_ia":     config_candidato["tipo_ia"],
                "modelo":      config_candidato["modelo"],
                "temperatura": config_candidato["temperatura"],
                "idioma":      config_candidato["idioma"],
                "fuente":      "UI",
            },
        )
        return True

    # ── Eliminación de agentes ────────────────────────────────────────────────

    async def eliminar_agente(self, agente_id: str) -> bool:
        """
        Elimina un agente del sistema en caliente.
        Flujo: valida existencia → elimina del registry → persiste config.json.
        Retorna True si fue eliminado, False si no existía.
        """
        if agente_id not in self.agentes:
            logger.error(
                "ELIMINAR_AGENTE: agente '%s' no existe.", agente_id,
                extra={"agente_id": agente_id},
            )
            return False

        del self.agentes[agente_id]
        self.config["agents"] = [
            a for a in self.config["agents"] if a.get("id") != agente_id
        ]

        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

        logger.info(
            "Agente eliminado del sistema.",
            extra={"evento": "AGENTE_ELIMINADO", "agente_id": agente_id},
        )
        return True

    # ── Actualización de agentes en caliente ──────────────────────────────────

    async def actualizar_agente(self, agente_id: str, data: dict) -> bool:
        """
        Actualiza los parámetros de un agente existente con validación Pydantic.
        Persiste los cambios en config.json si la validación pasa.
        Retorna True si fue actualizado, False si la validación falló o no existe.
        """
        if agente_id not in self.agentes:
            logger.error("ACTUALIZAR_AGENTE: agente '%s' no existe.", agente_id)
            return False

        ag = self.agentes[agente_id]
        resultado = ag.reload_config(data)   # snapshot + Pydantic + rollback

        if resultado:
            # Sincronizar config en memoria
            for ag_cfg in self.config["agents"]:
                if ag_cfg.get("id") == agente_id:
                    campos = ("nombre", "tipo_ia", "area", "modelo",
                              "temperatura", "idioma", "prompt_base",
                              "ubicacion", "siguiente_agente_id")
                    for campo in campos:
                        if campo in data:
                            ag_cfg[campo] = data[campo]
                    break

            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)

            logger.info(
                "ACTUALIZAR_AGENTE aplicado para '%s'.",
                agente_id,
                extra={"agente_id": agente_id},
            )

        return resultado

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
