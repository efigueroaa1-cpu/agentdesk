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
  "ollama:llama3.2"                 → Ollama local (Soberanía de Datos, ADR-0018)
  "ollama:mistral"                  → LM Studio / cualquier servidor local
                                       compatible con la API de OpenAI

Env vars necesarias por proveedor:
  GEMINI_API_KEY    → ya configurada
  OPENAI_API_KEY    → OpenAI
  DEEPSEEK_API_KEY  → DeepSeek (formato compatible OpenAI)
  ANTHROPIC_API_KEY → Claude
  GROQ_API_KEY      → Groq (tier gratuito muy generoso)
  AGENTDESK_OLLAMA_BASE_URL → Ollama/LM Studio (ADR-0018). Opcional: por
                              defecto http://localhost:11434/v1 (Ollama).
                              Sin API key real — el servidor local no la
                              exige, pero el SDK de OpenAI requiere enviar
                              alguna cadena no vacía.
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
    "ollama": [
        # Catálogo orientativo — los modelos REALMENTE disponibles dependen
        # de lo que el usuario haya descargado en su servidor local
        # (`ollama pull <modelo>`). No hay forma de listarlos sin consultar
        # el servidor en vivo; esta lista es solo para el selector de la UI.
        {"id": "ollama:llama3.2",                     "nombre": "Llama 3.2 (Ollama local)", "costo": "gratis", "velocidad": "depende del hardware"},
        {"id": "ollama:mistral",                      "nombre": "Mistral (Ollama local)",   "costo": "gratis", "velocidad": "depende del hardware"},
        {"id": "ollama:qwen2.5",                      "nombre": "Qwen 2.5 (Ollama local)",  "costo": "gratis", "velocidad": "depende del hardware"},
    ],
    "mock": [
        {"id": "mock:agentdesk-demo",                 "nombre": "Mock Determinista (Demo)", "costo": "gratis", "velocidad": "instantáneo"},
    ],
}

# Ollama/LM Studio (ADR-0018): servidor LOCAL compatible con la API de
# OpenAI. Sin este puerto no hay soberanía de datos real posible -- CUALQUIER
# otro proveedor de la cadena sale a internet.
OLLAMA_BASE_URL_DEFECTO = "http://localhost:11434/v1"


# ── MockProvider: Modo Demo / Dry-Run (soberanía de ejecución) ─────────────────
# AgentDesk debe poder funcionar, probarse y demostrarse SIN claves de API ni
# internet. Con AGENTDESK_MODE=mock|demo|dry-run TODA generación se resuelve
# localmente con respuestas deterministas (mismo prompt → misma respuesta),
# lo que permite tests gratis y reproducibles en el gate.

def modo_mock_activo() -> bool:
    """True si AgentDesk corre en Modo Demo/Dry-Run (sin claves ni red)."""
    return os.environ.get("AGENTDESK_MODE", "").lower() in {"mock", "demo", "dry-run", "dryrun"}


def respuesta_mock(modelo: str, prompt: str) -> str:
    """
    Respuesta determinista: se deriva por hash SHA-256 del prompt, así el mismo
    prompt produce siempre exactamente el mismo texto (asserts estables).

    Si el prompt pide un reporte JSON (el formato de realizar_tarea), la
    respuesta cumple ESTRICTAMENTE el schema ReporteAgente: todos los valores
    como texto, evidencia sin cifras >=1000 (nada que el GroundingGuard pueda
    marcar como alucinación) y honesta sobre el modo degradado — antes el mock
    devolvía texto plano, el parseo JSON fallaba 3 veces y todo agente que
    caía al mock abortaba con 'reporte invalido' (2026-07-19).
    """
    import hashlib
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    semilla = int(digest[:8], 16)
    tendencias = ["alza sostenida", "estable", "leve contracción", "recuperación gradual"]
    tendencia = tendencias[semilla % len(tendencias)]

    if "JSON" in prompt:
        import json as _json
        return _json.dumps({
            "resumen": (
                "Reporte en MODO DEGRADADO (sin proveedor de IA disponible; "
                "respuesta determinista local). No se realizó análisis "
                f"interpretativo de los datos. Tendencia nominal: {tendencia}. "
                f"Trazabilidad: sha256={digest[:16]}."
            ),
            "kpis": {
                "Modo de Operacion": "degradado (mock, sin red)",
                "Analisis Interpretativo": "no disponible",
                "Indice Determinista": f"{semilla % 100}/100",
            },
            "tabla": [
                ["Campo", "Valor"],
                ["Proveedor", str(modelo)],
                ["Modo", "degradado sin API"],
                ["Recomendacion", "reintentar cuando haya proveedor disponible"],
            ],
            "evidencia": {
                "Modo de Operacion": (
                    "respuesta generada localmente por el MockProvider; "
                    "no se citan cifras porque no hubo análisis real"
                ),
            },
        }, ensure_ascii=False)

    resumen_prompt = " ".join(prompt.split())[:120]
    return (
        f"[MOCK:{modelo}] Análisis determinista (Modo Demo, sin red).\n"
        f"Solicitud: {resumen_prompt}\n"
        f"Diagnóstico: tendencia con {tendencia}; "
        f"indicador compuesto {semilla % 100}/100.\n"
        f"Recomendación: mantener el plan vigente y revisar en el próximo ciclo.\n"
        f"Trazabilidad: sha256={digest[:16]}"
    )


async def _mock(modelo: str, prompt: str, temperature: float) -> str:
    return respuesta_mock(modelo, prompt)


async def _mock_stream(modelo: str, prompt: str, temperature: float):
    texto = respuesta_mock(modelo, prompt)
    for i in range(0, len(texto), 16):
        yield texto[i:i + 16]


def guardar_api_key(proveedor: str, api_key: str) -> dict:
    """
    Persiste la API key de un proveedor en el .env de AppData\\AgentDesk,
    la activa en el entorno del proceso y la respalda en el vault cifrado.
    (Extraído de core/api.py — la API solo valida el transporte.)
    """
    import pathlib as _pathlib
    env_key  = f"{proveedor.upper()}_API_KEY"
    _appdata = _pathlib.Path(os.environ.get("APPDATA", str(_pathlib.Path.home())))
    env_path = _appdata / "AgentDesk" / ".env"
    if not env_path.exists():
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("", encoding="utf-8")

    lines, found, new_lines = env_path.read_text(encoding="utf-8").splitlines(), False, []
    for line in lines:
        if line.startswith(f"{env_key}="):
            new_lines.append(f"{env_key}={api_key}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{env_key}={api_key}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[env_key] = api_key
    try:
        from core.key_vault import guardar_key_cifrada
        guardar_key_cifrada(env_key, api_key)
    except Exception:
        pass
    logger.info("API key configurada para proveedor: %s", proveedor.upper())
    return {"ok": True, "proveedor": proveedor.upper(), "env_key": env_key}


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
        # Ollama (ADR-0018) no exige API key -- el servidor local decide si
        # responde o no. Se marca "configurado" siempre (URL por defecto
        # sin variable), consistente con la politica Zero-Default (ADR-0016):
        # AUSENCIA de configuracion es un estado valido, no un bloqueo. Si el
        # servidor local no esta corriendo, la llamada real falla y la
        # cadena de resiliencia (ADR-0017) sigue al siguiente eslabon.
        "ollama":    True,
        "mock":      modo_mock_activo(),
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

    # Modo Demo/Dry-Run: intercepta TODOS los proveedores (cero red, cero costo)
    if proveedor == "mock" or modo_mock_activo():
        async for chunk in _mock_stream(modelo, prompt, temperature):
            yield chunk
    elif proveedor == "gemini":
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
    elif proveedor == "ollama":
        async for chunk in _ollama_stream(modelo, prompt, temperature):
            yield chunk
    else:
        raise ValueError(f"Proveedor desconocido: {proveedor!r}")


async def generate(model_id: str, prompt: str, temperature: float = 0.4,
                   prioridad: int = 2) -> str:
    """
    Función unificada de generación de texto con rate limiting.
    prioridad: 1=alta (chat), 2=media (análisis), 3=baja (batch automático)
    """
    resultado = await generate_con_uso(model_id, prompt, temperature, prioridad)
    return resultado["texto"]


def _uso_estimado(prompt: str, texto: str) -> dict:
    """
    Fallback cuando el SDK del proveedor no expone metadata real de uso
    (o el proveedor es el mock). Misma aproximación que auditoria_ia usa
    desde la Fase 7 (chars/4) — NUNCA se presenta como exacto.
    """
    entrada = len(prompt) // 4
    salida  = len(texto) // 4
    return {
        "tokens_entrada": entrada, "tokens_salida": salida,
        "tokens_total": entrada + salida, "tokens_exactos": False,
    }


async def generate_con_uso(model_id: str, prompt: str, temperature: float = 0.4,
                           prioridad: int = 2) -> dict:
    """
    Como generate(), pero retorna también el conteo de tokens (Fase 19,
    ADR-0017: FinOps IA). Cuando el SDK del proveedor expone uso real en la
    respuesta (OpenAI/Groq/DeepSeek: response.usage; Gemini:
    response.usage_metadata; Anthropic: message.usage) se usa ESE valor
    exacto (tokens_exactos=True); si no está disponible se degrada a la
    estimación chars/4 histórica (tokens_exactos=False) — nunca se rompe
    la generación por no poder contar tokens.

    Retorna {"texto", "proveedor", "modelo", "tokens_entrada",
    "tokens_salida", "tokens_total", "tokens_exactos"}.
    """
    proveedor, modelo = parse_model_id(model_id)

    # Modo Demo/Dry-Run: respuesta local determinista sin rate limiter ni red
    if proveedor == "mock" or modo_mock_activo():
        texto = await _mock(modelo, prompt, temperature)
        return {"texto": texto, "proveedor": "mock", "modelo": modelo,
                **_uso_estimado(prompt, texto)}

    _fn_map = {
        "gemini":    _gemini,
        "openai":    _openai,
        "deepseek":  _deepseek,
        "anthropic": _anthropic,
        "groq":      _groq,
        "ollama":    _ollama,
    }
    fn = _fn_map.get(proveedor)
    if fn is None:
        raise ValueError(f"Proveedor desconocido: {proveedor!r}.")

    # Rate limiting con cola inteligente
    try:
        from core.rate_limiter import llamada_protegida, Prioridad
        prio = Prioridad(prioridad) if prioridad in (1, 2, 3) else Prioridad.MEDIA
        texto, uso = await llamada_protegida(
            proveedor,
            lambda: fn(modelo, prompt, temperature),
            prio,
        )
    except ImportError:
        # Fallback sin rate limiter si no está disponible
        texto, uso = await fn(modelo, prompt, temperature)

    if uso is None:
        uso = _uso_estimado(prompt, texto)
    return {"texto": texto, "proveedor": proveedor, "modelo": modelo, **uso}


# ── Implementaciones por proveedor ─────────────────────────────────────────────
# Cada función retorna (texto, uso) — uso es un dict con tokens_entrada/
# tokens_salida/tokens_total/tokens_exactos=True cuando el SDK expone la
# metadata real, o None si no se pudo extraer (generate_con_uso degrada a
# la estimacion chars/4 en ese caso).

async def _gemini(modelo: str, prompt: str, temperature: float) -> tuple[str, dict | None]:
    from google import genai
    from google.genai import types
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client  = genai.Client(api_key=api_key)
    resp    = await client.aio.models.generate_content(
        model=modelo,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    texto = resp.text.strip()
    uso   = None
    try:
        um = resp.usage_metadata
        if um is not None:
            entrada = int(um.prompt_token_count or 0)
            salida  = int(um.candidates_token_count or 0)
            uso = {"tokens_entrada": entrada, "tokens_salida": salida,
                   "tokens_total": int(um.total_token_count or entrada + salida),
                   "tokens_exactos": True}
    except (AttributeError, TypeError):
        pass
    return texto, uso


async def _openai(modelo: str, prompt: str, temperature: float) -> tuple[str, dict | None]:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    resp   = await client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    texto = resp.choices[0].message.content.strip()
    return texto, _uso_openai_compatible(resp)


async def _deepseek(modelo: str, prompt: str, temperature: float) -> tuple[str, dict | None]:
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
    texto = resp.choices[0].message.content.strip()
    return texto, _uso_openai_compatible(resp)


async def _anthropic(modelo: str, prompt: str, temperature: float) -> tuple[str, dict | None]:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg    = await client.messages.create(
        model=modelo,
        max_tokens=4096,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    texto = msg.content[0].text.strip()
    uso   = None
    try:
        entrada = int(msg.usage.input_tokens or 0)
        salida  = int(msg.usage.output_tokens or 0)
        uso = {"tokens_entrada": entrada, "tokens_salida": salida,
               "tokens_total": entrada + salida, "tokens_exactos": True}
    except (AttributeError, TypeError):
        pass
    return texto, uso


async def _groq(modelo: str, prompt: str, temperature: float) -> tuple[str, dict | None]:
    from groq import AsyncGroq
    client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))
    resp   = await client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=min(temperature, 1.0),  # Groq max temp=1.0
    )
    texto = resp.choices[0].message.content.strip()
    return texto, _uso_openai_compatible(resp)


async def _ollama(modelo: str, prompt: str, temperature: float) -> tuple[str, dict | None]:
    """
    Ollama / LM Studio (ADR-0018, Soberanía de Datos): servidor LOCAL
    compatible con la API de OpenAI — mismo patrón que _deepseek(), solo
    cambia base_url. Sin internet: si el servidor local no está corriendo,
    la conexión falla como cualquier otro proveedor caído y la cadena de
    resiliencia (ADR-0017) sigue al siguiente eslabón (mock).
    """
    from openai import AsyncOpenAI
    base_url = os.environ.get("AGENTDESK_OLLAMA_BASE_URL", OLLAMA_BASE_URL_DEFECTO)
    client = AsyncOpenAI(
        api_key=os.environ.get("AGENTDESK_OLLAMA_API_KEY", "ollama"),  # el servidor local no la valida
        base_url=base_url,
    )
    resp = await client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    texto = resp.choices[0].message.content.strip()
    return texto, _uso_openai_compatible(resp)


def _uso_openai_compatible(resp) -> dict | None:
    """Extrae uso real de una respuesta con forma OpenAI (OpenAI/Groq/DeepSeek)."""
    try:
        u = resp.usage
        if u is None:
            return None
        entrada = int(getattr(u, "prompt_tokens", 0) or 0)
        salida  = int(getattr(u, "completion_tokens", 0) or 0)
        total   = int(getattr(u, "total_tokens", entrada + salida) or entrada + salida)
        return {"tokens_entrada": entrada, "tokens_salida": salida,
                "tokens_total": total, "tokens_exactos": True}
    except (AttributeError, TypeError):
        return None


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


async def _ollama_stream(modelo: str, prompt: str, temperature: float):
    """Ollama / LM Studio en streaming (ADR-0018) — mismo patrón que _deepseek_stream()."""
    from openai import AsyncOpenAI
    base_url = os.environ.get("AGENTDESK_OLLAMA_BASE_URL", OLLAMA_BASE_URL_DEFECTO)
    client = AsyncOpenAI(
        api_key=os.environ.get("AGENTDESK_OLLAMA_API_KEY", "ollama"),
        base_url=base_url,
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
