# -*- coding: utf-8 -*-
"""
core/orchestrator_chat_tools_stream.py — Tool-calling nativo en streaming (chat_con_herramientas_stream).

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

logger = logging.getLogger(__name__)


class AgentChatToolsStreamMixin:
    """Tool-calling nativo en streaming (chat_con_herramientas_stream)."""

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
