"""
core/services/insights_service.py — Resúmenes ejecutivos con IA (ADR-0003).

Briefing web (Tavily + resumen Groq en español) y resumen ejecutivo del
dashboard. Extraído de core/api.py; sin FastAPI.
"""
from __future__ import annotations

import asyncio
import logging

from core.services import analytics_service

logger = logging.getLogger(__name__)


async def _groq_resumen(prompt: str, max_tokens: int, timeout_s: float) -> str:
    """
    Resumen vía cadena resiliente (Fase 8): Groq → Gemini → OpenAI → Mock,
    con Circuit Breaker por proveedor. Nunca deja al dashboard sin respuesta.
    (Conserva el nombre histórico; max_tokens/timeout_s los gobierna la cadena.)
    """
    from core.services.llm_service import llm_service
    temperatura = 0.3 if max_tokens <= 300 else 0.4
    # Sin timeout externo: la cadena ya limita cada eslabón (30 s) y degrada
    # a mock antes que dejar colgado al dashboard.
    resultado = await llm_service.generar(prompt, temperatura=temperatura, prioridad=2)
    return resultado["texto"]


async def briefing(tema: str, agente_id: str = "") -> dict:
    """Busca información web sobre el tema (Tavily) y la resume en español."""
    if not tema.strip():
        return {"tema": "", "query": "", "agente": {}, "answer": "", "resultados": []}

    from core.tools import _TAVILY_KEY
    import httpx

    agentes_cfg = analytics_service._agentes_config()
    agente_info: dict = {}
    if agente_id and agente_id in agentes_cfg:
        a = agentes_cfg[agente_id]
        agente_info = {
            "id":     agente_id,
            "nombre": a.get("nombre", agente_id),
            "area":   a.get("area", ""),
        }

    area  = agente_info.get("area", "")
    query = f"{tema.strip()} {area}".strip() if area else tema.strip()

    try:
        async with httpx.AsyncClient(timeout=22) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key":             _TAVILY_KEY,
                    "query":               query,
                    "max_results":         8,
                    "search_depth":        "advanced",
                    "include_answer":      True,
                    "include_raw_content": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        resultados = [
            {
                "titulo":  r.get("title", ""),
                "url":     r.get("url", ""),
                "dominio": (r.get("url", "").split("/")[2] if r.get("url", "").startswith("http") else ""),
                "snippet": (r.get("content") or "")[:380],
                "score":   round(r.get("score", 0), 2),
            }
            for r in data.get("results", [])
        ]

        # Resumen en español con Groq; fallback al answer de Tavily
        answer_es = ""
        try:
            snippets_text = "\n\n".join(
                f"[{r['dominio']}] {r['snippet']}" for r in resultados[:5] if r["snippet"]
            )
            llm_prompt = (
                f"Basándote en esta información sobre \"{tema.strip()}\", escribe UN PÁRRAFO BREVE "
                f"(3-5 oraciones) en ESPAÑOL con los datos más importantes: resultados financieros, "
                f"producción, noticias recientes, o lo que sea más relevante.\n\n"
                f"INFORMACIÓN:\n{snippets_text}\n\n"
                f"REGLAS: Responde SOLO en español. Sin introducción. Sin títulos. Solo el párrafo directo."
            )
            answer_es = await _groq_resumen(llm_prompt, max_tokens=300, timeout_s=12)
        except Exception as _llm_e:
            logger.warning("briefing llm summary: %s", _llm_e)
        if not answer_es:
            answer_es = data.get("answer", "")

        return {
            "tema":       tema.strip(),
            "query":      query,
            "agente":     agente_info,
            "answer":     answer_es,
            "resultados": resultados,
        }
    except Exception as _e:
        logger.warning("briefing: %s", _e)
        return {"tema": tema, "query": query, "agente": agente_info,
                "answer": "", "resultados": [], "error": str(_e)}


async def resumen_ia(dias: int = 30, agente_id: str = "") -> dict:
    """Resumen ejecutivo en español del uso del sistema (datos reales + LLM)."""
    base      = analytics_service.dashboard_datos(agente_id=agente_id, dias=dias)
    kpis      = base.get("kpis", {})
    serie     = base.get("actividad_serie", [])
    rep_serie = base.get("reportes_serie", [])

    last7 = sum(d["mensajes"] for d in serie[-7:])
    prev7 = sum(d["mensajes"] for d in serie[-14:-7])
    chg7  = round((last7 - prev7) / prev7 * 100) if prev7 > 0 else None
    reps_sem = sum(d["reportes"] for d in rep_serie[-7:])

    ctx = (
        f"Sistema de agentes IA · últimos {dias} días:\n"
        f"- Sesiones: {kpis.get('sesiones',0)}\n"
        f"- Mensajes totales: {kpis.get('mensajes',0)}\n"
        f"- Mensajes últimos 7 días: {last7}"
        + (f" ({'+' if (chg7 or 0)>=0 else ''}{chg7}% vs semana anterior)" if chg7 is not None else "") + "\n"
        f"- Mensajes por sesión: {round(kpis.get('mensajes',0)/kpis.get('sesiones',1),1) if kpis.get('sesiones',0)>0 else 0}\n"
        f"- Reportes PDF totales: {kpis.get('reportes',0)}\n"
        f"- Reportes PDF última semana: {reps_sem}\n"
    )
    if agente_id:
        ctx += f"- Filtrado para agente: {agente_id}\n"

    prompt = (
        f"Eres un analista de productividad. Analiza estos datos de uso de un sistema de agentes IA "
        f"y escribe un resumen ejecutivo en ESPAÑOL con 3 párrafos cortos:\n\n"
        f"1. Estado actual y tendencia de actividad\n"
        f"2. Eficiencia y productividad (reportes, calidad de sesiones)\n"
        f"3. Una recomendación concreta y accionable\n\n"
        f"DATOS:\n{ctx}\n\n"
        f"REGLAS: Solo en español. Sin títulos ni numeración. Lenguaje claro, directo, sin jerga técnica."
    )

    try:
        resumen = await _groq_resumen(prompt, max_tokens=450, timeout_s=18)
        return {"resumen": resumen}
    except Exception as e:
        logger.warning("resumen_ia: %s", e)
        return {"resumen": "", "error": str(e)}
