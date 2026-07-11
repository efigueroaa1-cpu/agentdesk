"""
core/providers.py — Capa de abstracción multi-proveedor de LLM.

Formato de model_id:
  "models/gemini-2.5-flash"          → Gemini (backward compatible, sin prefijo)
  "gemini:models/gemini-2.5-flash"   → Gemini (con prefijo explícito)
  "openai:gpt-4o"                    → OpenAI
  "openai:gpt-4o-mini"               → OpenAI (más barato)
  "deepseek:deepseek-chat"           → DeepSeek
  "deepseek:deepseek-reasoner"       → DeepSeek R1
  "anthropic:claude-3-5-sonnet-20241022" → Claude
  "anthropic:claude-3-haiku-20240307"    → Claude Haiku (barato)
  "groq:llama-3.3-70b-versatile"    → Groq/LLaMA (MUY rápido y GRATUITO)
  "groq:mixtral-8x7b-32768"         → Groq/Mixtral

Env vars necesarias por proveedor:
  GEMINI_API_KEY    → ya configurada
  OPENAI_API_KEY    → OpenAI
  DEEPSEEK_API_KEY  → DeepSeek (formato compatible OpenAI)
  ANTHROPIC_API_KEY → Claude
  GROQ_API_KEY      → Groq (tier gratuito muy generoso)
"""

from __future__ import annotations
import os
import logging

logger = logging.getLogger(__name__)

# Catálogo de modelos disponibles por proveedor
CATALOGO: dict[str, list[dict]] = {
    "gemini": [
        {"id": "gemini:models/gemini-2.5-flash",      "nombre": "Gemini 2.5 Flash",        "costo": "bajo",   "velocidad": "rápido"},
        {"id": "gemini:models/gemini-1.5-flash",       "nombre": "Gemini 1.5 Flash",         "costo": "bajo",   "velocidad": "rápido"},
        {"id": "gemini:models/gemini-1.5-flash-8b",    "nombre": "Gemini 1.5 Flash 8B",      "costo": "mínimo", "velocidad": "muy rápido"},
        {"id": "gemini:models/gemini-1.5-pro",         "nombre": "Gemini 1.5 Pro",           "costo": "medio",  "velocidad": "normal"},
    ],
    "openai": [
        {"id": "openai:gpt-4o",                        "nombre": "GPT-4o",                   "costo": "alto",   "velocidad": "normal"},
        {"id": "openai:gpt-4o-mini",                   "nombre": "GPT-4o Mini",              "costo": "bajo",   "velocidad": "rápido"},
        {"id": "openai:gpt-4.1",                       "nombre": "GPT-4.1",                  "costo": "alto",   "velocidad": "normal"},
        {"id": "openai:o1-mini",                       "nombre": "o1 Mini (razonamiento)",   "costo": "medio",  "velocidad": "lento"},
    ],
    "deepseek": [
        {"id": "deepseek:deepseek-chat",               "nombre": "DeepSeek Chat V3",         "costo": "muy bajo","velocidad": "rápido"},
        {"id": "deepseek:deepseek-reasoner",           "nombre": "DeepSeek R1 (razona)",     "costo": "bajo",   "velocidad": "normal"},
    ],
    "anthropic": [
        {"id": "anthropic:claude-opus-4-5",            "nombre": "Claude Opus 4.5",          "costo": "muy alto","velocidad": "lento"},
        {"id": "anthropic:claude-sonnet-4-5",          "nombre": "Claude Sonnet 4.5",        "costo": "medio",  "velocidad": "normal"},
        {"id": "anthropic:claude-haiku-4-5",           "nombre": "Claude Haiku 4.5",         "costo": "bajo",   "velocidad": "rápido"},
    ],
    "groq": [
        {"id": "groq:llama-3.3-70b-versatile",        "nombre": "LLaMA 3.3 70B (Groq)",    "costo": "gratis", "velocidad": "muy rápido"},
        {"id": "groq:llama-3.1-8b-instant",           "nombre": "LLaMA 3.1 8B (Groq)",     "costo": "gratis", "velocidad": "ultrarrápido"},
        {"id": "groq:mixtral-8x7b-32768",             "nombre": "Mixtral 8x7B (Groq)",      "costo": "gratis", "velocidad": "rápido"},
        {"id": "groq:gemma2-9b-it",                   "nombre": "Gemma2 9B (Groq)",         "costo": "gratis", "velocidad": "rápido"},
    ],
}


def parse_model_id(model_id: str) -> tuple[str, str]:
    """Devuelve (proveedor, modelo_real) desde un model_id."""
    if ":" in model_id and not model_id.startswith("models/"):
        proveedor, modelo = model_id.split(":", 1)
        return proveedor.lower().strip(), modelo.strip()
    # Backward compatible: sin prefijo = gemini
    return "gemini", model_id


def proveedores_configurados() -> dict[str, bool]:
    """Devuelve qué proveedores tienen API key en el entorno."""
    return {
        "gemini":    bool(os.environ.get("GEMINI_API_KEY")),
        "openai":    bool(os.environ.get("OPENAI_API_KEY")),
        "deepseek":  bool(os.environ.get("DEEPSEEK_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "groq":      bool(os.environ.get("GROQ_API_KEY")),
    }


def modelos_disponibles() -> list[dict]:
    """Retorna todos los modelos de los proveedores configurados."""
    config = proveedores_configurados()
    resultado = []
    for proveedor, modelos in CATALOGO.items():
        for m in modelos:
            resultado.append({
                **m,
                "proveedor":   proveedor,
                "disponible":  config.get(proveedor, False),
            })
    return resultado


from typing import AsyncGenerator

async def generate_stream(model_id: str, prompt: str,
                           temperature: float = 0.4) -> AsyncGenerator[str, None]:
    """
    Versión streaming de generate() — devuelve chunks de texto conforme llegan.
    Usar con: async for chunk in generate_stream(model_id, prompt): ...
    """
    proveedor, modelo = parse_model_id(model_id)

    if proveedor == "gemini":
        async for chunk in _gemini_stream(modelo, prompt, temperature):
            yield chunk
    elif proveedor == "openai":
        async for chunk in _openai_stream(modelo, prompt, temperature):
            yield chunk
    elif proveedor == "deepseek":
        async for chunk in _deepseek_stream(modelo, prompt, temperature):
            yield chunk
    elif proveedor == "anthropic":
        async for chunk in _anthropic_stream(modelo, prompt, temperature):
            yield chunk
    elif proveedor == "groq":
        async for chunk in _groq_stream(modelo, prompt, temperature):
            yield chunk
    else:
        raise ValueError(f"Proveedor desconocido: {proveedor!r}")


async def generate(model_id: str, prompt: str, temperature: float = 0.4,
                   prioridad: int = 2) -> str:
    """
    Función unificada de generación de texto con rate limiting.
    prioridad: 1=alta (chat), 2=media (análisis), 3=baja (batch automático)
    """
    proveedor, modelo = parse_model_id(model_id)

    _fn_map = {
        "gemini":    _gemini,
        "openai":    _openai,
        "deepseek":  _deepseek,
        "anthropic": _anthropic,
        "groq":      _groq,
    }
    fn = _fn_map.get(proveedor)
    if fn is None:
        raise ValueError(f"Proveedor desconocido: {proveedor!r}.")

    # Rate limiting con cola inteligente
    try:
        from core.rate_limiter import llamada_protegida, Prioridad
        prio = Prioridad(prioridad) if prioridad in (1, 2, 3) else Prioridad.MEDIA
        return await llamada_protegida(
            proveedor,
            lambda: fn(modelo, prompt, temperature),
            prio,
        )
    except ImportError:
        # Fallback sin rate limiter si no está disponible
        return await fn(modelo, prompt, temperature)


# ── Implementaciones por proveedor ─────────────────────────────────────────────

async def _gemini(modelo: str, prompt: str, temperature: float) -> str:
    from google import genai
    from google.genai import types
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client  = genai.Client(api_key=api_key)
    resp    = await client.aio.models.generate_content(
        model=modelo,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    return resp.text.strip()


async def _openai(modelo: str, prompt: str, temperature: float) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    resp   = await client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


async def _deepseek(modelo: str, prompt: str, temperature: float) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com",
    )
    resp = await client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


async def _anthropic(modelo: str, prompt: str, temperature: float) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg    = await client.messages.create(
        model=modelo,
        max_tokens=4096,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


async def _groq(modelo: str, prompt: str, temperature: float) -> str:
    from groq import AsyncGroq
    client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))
    resp   = await client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=min(temperature, 1.0),  # Groq max temp=1.0
    )
    return resp.choices[0].message.content.strip()


# ── Implementaciones STREAMING por proveedor ──────────────────────────────────

async def _groq_stream(modelo: str, prompt: str, temperature: float):
    """Groq streaming con tool calling en dos fases.

    Fase 1 (no-streaming): el modelo decide si necesita herramientas.
    Fase 2 (streaming): respuesta final con datos reales incorporados.
    """
    import json as _json
    from groq import AsyncGroq
    from core.tools import TOOLS_SCHEMA, ejecutar_herramienta

    client   = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))
    messages = [{"role": "user", "content": prompt}]

    # ── Fase 1: loop de tool calling (no-streaming) ───────────────────────────
    MAX_PASOS = 5
    try:
        for _ in range(MAX_PASOS):
            resp   = await client.chat.completions.create(
                model=modelo,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                temperature=min(temperature, 1.0),
                max_tokens=4096,
            )
            msg    = resp.choices[0].message
            finish = resp.choices[0].finish_reason

            if finish == "stop" or not msg.tool_calls:
                break  # sin herramientas → ir directo a Fase 2

            # Registrar mensaje del asistente con tool_calls
            asst = {"role": "assistant", "content": msg.content or ""}
            asst["tool_calls"] = [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
            messages.append(asst)

            # Ejecutar cada herramienta y agregar resultado
            for tc in msg.tool_calls:
                nombre = tc.function.name
                try:
                    args = _json.loads(tc.function.arguments or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except Exception:
                    args = {}
                logger.info("Tool call: %s(%s)", nombre, args)
                resultado = await ejecutar_herramienta(nombre, args)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      str(resultado)[:4000],
                })

    except Exception as exc:
        logger.warning("_groq_stream fase-1 tools: %s — usando stream directo", exc)
        messages = [{"role": "user", "content": prompt}]  # reset sin tools

    # ── Fase 2: respuesta final en streaming ──────────────────────────────────
    stream = await client.chat.completions.create(
        model=modelo,
        messages=messages,
        temperature=min(temperature, 1.0),
        max_tokens=2048,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def _openai_stream(modelo: str, prompt: str, temperature: float):
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    stream = await client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def _deepseek_stream(modelo: str, prompt: str, temperature: float):
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com",
    )
    stream = await client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def _anthropic_stream(modelo: str, prompt: str, temperature: float):
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    async with client.messages.stream(
        model=modelo, max_tokens=4096, temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _gemini_stream(modelo: str, prompt: str, temperature: float):
    """Gemini: simula streaming dividiendo la respuesta completa."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    resp   = await client.aio.models.generate_content(
        model=modelo, contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    text = resp.text
    for i in range(0, len(text), 4):
        yield text[i:i+4]
