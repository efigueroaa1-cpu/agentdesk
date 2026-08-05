# -*- coding: utf-8 -*-
"""
core/orchestrator_chat_tools.py — Tool-calling nativo (chat_con_herramientas).

Extraido de core/orchestrator.py (2026-07-27, Strangler Fig v1.3, orchestrator
incremento 4/N). Mixin de AgentBase: accede via self a los atributos de
__init__ (nombre/modelo/temperatura/prompt_base/idioma/area) y a los metodos
que quedan en AgentBase (chat_libre/chat_libre_stream/_contexto_harnesses/
_criticar_respuesta). Imports pesados (TOOLS_SCHEMA/llm_service/SDKs) locales
por metodo. Cubierto por tests/audit/test_audit_trail, collaboration/
test_delegation, harnesses/test_memoria_en_realizar_tarea.
"""
import json
import logging
import os

# Logger bajo "core.orchestrator" (no __name__): el codigo extraido de
# core/orchestrator.py siempre logueo ahi; dashboards y auditoria forense
# filtran por ese nombre (2026-07-27, contrato operacional preservado).
logger = logging.getLogger("core.orchestrator")


class AgentChatToolsMixin:
    """Tool-calling nativo (chat_con_herramientas)."""

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
