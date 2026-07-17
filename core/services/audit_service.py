"""
core/services/audit_service.py — Motor de Auditoría Forense IA (ADR-0007/0014;
FinOps IA extendido en Fase 19, ADR-0017; retención y purga en Fase 20, ADR-0018).

Ante la infalibilidad imposible: observabilidad total. Cada interacción de
agente (entrada, contexto RECUPERADO por los HATs, modelo, herramientas,
veredicto de CADA guardrail y salida) queda registrada con timestamp en la
tabla `auditoria_ia` (SQLite/PostgreSQL, ADR-0005/0013) para auditoría en
sectores regulados.

Principios:
  - Best-effort: la auditoría JAMÁS rompe la interacción que registra
    (errores propios se loggean y se sigue).
  - Truncado defensivo: prompts/respuestas se acotan para no inflar la DB.
  - Tokens: EXACTOS cuando el proveedor los expone (Fase 19: OpenAI/Groq/
    DeepSeek/Anthropic vía `usage`, Gemini vía `usage_metadata`), estimados
    por caracteres/4 en caso contrario (mock, o si el SDK no los expuso).
    `tokens_exactos` en cada fila deja explícito cuál fue el caso — nunca
    se presenta una estimación como si fuera exacta.
  - Costo en USD: aproximación de tablero (tarifa combinada entrada+salida
    por proveedor, ver _USD_POR_1K_TOKENS) — para FinOps de orientación,
    no reemplaza la factura real de cada proveedor.
  - Higiene de PII (ADR-0014): el user_id real se guarda en la DB (RBAC y
    aislamiento de memoria de HATs, ADR-0010, lo necesitan tal cual) pero
    NUNCA en texto plano en los logs de aplicación — ahí solo su hash.
  - Retención (Fase 20, ADR-0018): auditoría total no significa auditoría
    ETERNA — en sectores regulados la retención indefinida de PII es, ella
    misma, un riesgo de cumplimiento. `purgar_registros_antiguos()` anonimiza
    (no borra la fila -- la traza de "que paso" sigue existiendo para
    conteo/series historicas) las filas mas viejas que N dias, configurable
    via `AGENTDESK_AUDITORIA_RETENCION_DIAS`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json as _json
import logging
import os

logger = logging.getLogger(__name__)

MAX_TEXTO = 4000   # caracteres conservados de prompt/respuesta/contexto_hats

# Retencion de auditoria (Fase 20, ADR-0018): dias que una fila conserva su
# contenido en claro antes de ser anonimizada. Zero-Default (ADR-0016): la
# AUSENCIA de configuracion es valida (usa este default razonable para
# sectores regulados); lo que se rechaza es un valor invalido, no la ausencia.
RETENCION_DIAS_DEFECTO = 365


def _retencion_dias_configurada() -> int:
    valor = os.environ.get("AGENTDESK_AUDITORIA_RETENCION_DIAS", "")
    if not valor:
        return RETENCION_DIAS_DEFECTO
    try:
        dias = int(valor)
    except ValueError:
        logger.warning(
            "AUDITORIA_SEGURIDAD: AGENTDESK_AUDITORIA_RETENCION_DIAS=%r invalido "
            "(no es entero) — usando default %d dias", valor, RETENCION_DIAS_DEFECTO,
        )
        return RETENCION_DIAS_DEFECTO
    if dias <= 0:
        logger.warning(
            "AUDITORIA_SEGURIDAD: AGENTDESK_AUDITORIA_RETENCION_DIAS=%d invalido "
            "(debe ser > 0) — usando default %d dias", dias, RETENCION_DIAS_DEFECTO,
        )
        return RETENCION_DIAS_DEFECTO
    return dias

# Precios aproximados en USD por 1000 tokens (Fase 19, ADR-0017). Tarifa
# COMBINADA entrada+salida a modo de estimación de tablero: los precios
# reales varían por modelo específico dentro de cada proveedor y cambian
# con el tiempo — esto es una aproximación para FinOps, nunca una factura.
_USD_POR_1K_TOKENS = {
    "groq":      0.0,       # tier gratuito
    "gemini":    0.00015,
    "openai":    0.0015,
    "deepseek":  0.0003,
    "anthropic": 0.006,
    "mock":      0.0,
}
_USD_POR_1K_TOKENS_DEFECTO = 0.001   # proveedor desconocido: estimación conservadora


def _estimar_tokens(*textos: str | None) -> int:
    return sum(len(t) for t in textos if t) // 4


def _estimar_costo_usd(proveedor: str, tokens_total: int) -> float:
    tarifa = _USD_POR_1K_TOKENS.get((proveedor or "").lower(), _USD_POR_1K_TOKENS_DEFECTO)
    return round((max(tokens_total, 0) / 1000) * tarifa, 6)


def _hash_pii(valor: str) -> str:
    """
    Hash corto y no reversible para identificar un usuario en LOGS DE TEXTO
    (ADR-0014). La base de datos SIGUE guardando el user_id real —lo
    necesitan RBAC y el aislamiento de memoria por usuario de ADR-0010—,
    pero los logs de aplicación (potencialmente exportados a un agregador
    externo) nunca deben imprimir el identificador en claro.
    """
    if not valor:
        return "anonimo"
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()[:12]


def registrar_interaccion(
    *,
    tipo: str,                       # chat | chat_stream | tarea | delegacion
    agente_id: str,
    prompt: str,
    respuesta: str = "",
    user_id: str = "anonimo",
    contexto: str = "",
    contexto_hats: str = "",         # memoria semantica RECUPERADA e inyectada (ADR-0014)
    modelo: str = "",
    proveedor: str = "",
    herramientas: list[str] | None = None,
    veredicto_guardrail: str = "no_aplica",
    guardrails: list[dict] | None = None,   # veredicto de CADA guardrail evaluado
    duracion_s: float | None = None,
    exitoso: bool = True,
    proyecto_id: str = "",           # ambito Hermes (ADR-0023); "" = global
    tokens_reales: dict | None = None,   # {"tokens_total", "tokens_exactos"} — Fase 19
) -> int | None:
    """Persiste una traza de auditoría forense completa. Retorna el id, o None si falló."""
    # FinOps IA (Fase 19, ADR-0017): usar el conteo EXACTO del proveedor
    # cuando llm_service.generar()/DelegationService lo propagaron; si no
    # (mock, o una interacción que no pasó por la cadena de resiliencia),
    # se degrada a la estimación chars/4 histórica de la Fase 7 — el flag
    # tokens_exactos deja constancia de cuál de los dos casos fue.
    if tokens_reales and tokens_reales.get("tokens_total") is not None:
        tokens_total   = int(tokens_reales["tokens_total"])
        tokens_exactos = bool(tokens_reales.get("tokens_exactos", False))
    else:
        tokens_total   = _estimar_tokens(prompt, respuesta, contexto_hats)
        tokens_exactos = False
    costo_usd = _estimar_costo_usd(proveedor, tokens_total)

    try:
        from core.database import AuditoriaIA, get_session
        with get_session() as s:
            fila = AuditoriaIA(
                tipo=tipo,
                user_id=(user_id or "anonimo")[:64],
                agente_id=(agente_id or "")[:64],
                proveedor=proveedor[:24],
                modelo=modelo[:96],
                prompt=(prompt or "")[:MAX_TEXTO],
                contexto=(contexto or "")[:1000],
                contexto_hats=(contexto_hats or "")[:MAX_TEXTO],
                respuesta=(respuesta or "")[:MAX_TEXTO],
                herramientas_json=_json.dumps(herramientas or [], ensure_ascii=False),
                costo_estimado=tokens_total,
                tokens_exactos=tokens_exactos,
                costo_usd_estimado=costo_usd,
                veredicto_guardrail=veredicto_guardrail[:32],
                guardrails_json=_json.dumps(guardrails or [], ensure_ascii=False),
                duracion_s=duracion_s,
                exitoso=exitoso,
            )
            s.add(fila)
            s.commit()
            logger.info(
                "AUDITORIA_IA: %s registrado — user_hash=%s agente=%s proveedor=%s "
                "tokens%s=%d costo_usd~%.6f veredicto=%s",
                tipo, _hash_pii(fila.user_id), fila.agente_id, fila.proveedor or "?",
                "" if tokens_exactos else "~", tokens_total, costo_usd,
                fila.veredicto_guardrail,
            )
            _id = fila.id
    except Exception as exc:
        logger.warning("AUDITORIA_IA: fallo al registrar (%s) — la interaccion continua", exc)
        return None

    # Metricas Prometheus (ADR-0014): fuera del bloque de sesion, best-effort
    # independiente — un fallo aqui nunca debe invalidar la traza ya guardada.
    try:
        from core.metrics_prometheus import registrar_interaccion as _metricas
        _metricas(tipo=tipo, exitoso=exitoso, agente_id=agente_id,
                  tokens=tokens_total, tokens_exactos=tokens_exactos,
                  costo_usd=costo_usd, proveedor=proveedor, duracion_s=duracion_s)
    except Exception as exc:
        logger.warning("AUDITORIA_IA: metricas Prometheus no actualizadas (%s)", exc)

    # Memoria Hermes (Fase 25, ADR-0023): las interacciones exitosas se
    # siembran en la memoria vectorial persistente para recuerdo entre
    # sesiones. Best-effort independiente, mismo principio que Prometheus.
    if exitoso and prompt and respuesta:
        try:
            from core.vector_store import PROYECTO_GLOBAL, hermes
            hermes().guardar(
                f"Pregunta: {prompt[:600]}\nRespuesta: {respuesta[:1200]}",
                user_id=(user_id or "anonimo")[:64],
                proyecto_id=(proyecto_id or PROYECTO_GLOBAL)[:64],
                agente_id=(agente_id or "")[:64],
                tipo="interaccion",
            )
        except Exception as exc:
            logger.warning("AUDITORIA_IA: memoria Hermes no sembrada (%s)", exc)

    return _id


def consultar(
    agente_id: str | None = None,
    user_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Trazas más recientes primero, filtrables por agente y usuario."""
    from core.database import AuditoriaIA, get_session
    limit = max(1, min(500, int(limit)))
    with get_session() as s:
        q = s.query(AuditoriaIA).order_by(AuditoriaIA.ts.desc())
        if agente_id:
            q = q.filter(AuditoriaIA.agente_id == agente_id)
        if user_id:
            q = q.filter(AuditoriaIA.user_id == user_id)
        return [r.to_dict() for r in q.limit(limit).all()]


def resumen_costos(limit_dias: int = 30) -> dict:
    """Tokens y costo USD estimado por agente (ventana N días) — FinOps IA (ADR-0017)."""
    from datetime import timedelta
    from core.database import AuditoriaIA, get_session
    from core.timeutil import utcnow
    desde = utcnow() - timedelta(days=limit_dias)
    with get_session() as s:
        filas = s.query(AuditoriaIA).filter(AuditoriaIA.ts >= desde).all()
    por_agente: dict[str, dict] = {}
    costo_usd_total = 0.0
    for f in filas:
        d = por_agente.setdefault(f.agente_id or "?", {
            "interacciones": 0, "tokens": 0, "tokens_exactos": 0, "costo_usd": 0.0,
        })
        d["interacciones"]  += 1
        d["tokens"]         += f.costo_estimado or 0
        d["tokens_exactos"] += 1 if f.tokens_exactos else 0
        d["costo_usd"]      += f.costo_usd_estimado or 0.0
        costo_usd_total     += f.costo_usd_estimado or 0.0
    for d in por_agente.values():
        d["costo_usd"] = round(d["costo_usd"], 6)
    return {"dias": limit_dias, "total": len(filas),
            "costo_usd_total": round(costo_usd_total, 6), "por_agente": por_agente}


_ANONIMIZADO = "[purgado por retencion]"


def purgar_registros_antiguos(dias: int | None = None) -> int:
    """
    Política de retención (Fase 20, ADR-0018): ANONIMIZA (no borra la fila)
    las trazas de auditoría más viejas que `dias` (o el configurado via
    AGENTDESK_AUDITORIA_RETENCION_DIAS si no se pasa explícito).

    Anonimizar en vez de DELETE es deliberado: la fila y sus columnas
    numéricas (tokens, costo_usd, veredicto_guardrail, duracion_s, ts)
    siguen existiendo para series históricas de FinOps/SLO — lo que se
    purga es el contenido con PII/texto libre (prompt, respuesta, contexto,
    contexto_hats, user_id real). Esto también es lo que hace que la purga
    NO pueda "corromper" la base: nunca cambia el conteo de filas ni el
    schema, solo el contenido de columnas ya existentes — verificable
    comparando `SELECT COUNT(*)` antes/después.

    Retorna el número de filas anonimizadas (0 si no había ninguna vieja,
    nunca lanza — best-effort, igual que el resto de este módulo).
    """
    from datetime import timedelta
    from core.database import AuditoriaIA, get_session
    from core.timeutil import utcnow

    dias_efectivos = dias if dias is not None else _retencion_dias_configurada()
    corte = utcnow() - timedelta(days=dias_efectivos)
    try:
        with get_session() as s:
            filas = (
                s.query(AuditoriaIA)
                .filter(AuditoriaIA.ts < corte)
                .filter(AuditoriaIA.user_id != _ANONIMIZADO[:64])
                .all()
            )
            for fila in filas:
                fila.user_id       = _ANONIMIZADO[:64]
                fila.prompt         = _ANONIMIZADO
                fila.respuesta      = _ANONIMIZADO
                fila.contexto       = _ANONIMIZADO
                fila.contexto_hats  = _ANONIMIZADO
                fila.herramientas_json = "[]"
                fila.guardrails_json   = "[]"
            s.commit()
            n = len(filas)
    except Exception as exc:
        logger.error("AUDITORIA_SEGURIDAD: purga de retencion fallo (%s)", exc)
        return 0

    if n:
        logger.warning(
            "AUDITORIA_SEGURIDAD: purga de retencion anonimizo %d fila(s) "
            "anteriores a %s (retencion=%d dias)", n, corte.isoformat(), dias_efectivos,
        )
    return n


INTERVALO_PURGA_S = 24 * 3600.0   # una vez al dia alcanza para una politica de retencion en dias


async def iniciar_monitor_purga(intervalo_s: float = INTERVALO_PURGA_S) -> None:
    """
    Loop de fondo (mismo patrón que `alert_service.iniciar_monitor()` y
    `kill_switch.iniciar_monitor()`): corre `purgar_registros_antiguos()`
    periódicamente hasta que la tarea se cancele. Registrado como
    `asyncio.create_task()` en `core/api/__init__.py::startup()`.
    """
    while True:
        try:
            purgar_registros_antiguos()
        except Exception as exc:
            logger.warning("AUDITORIA_SEGURIDAD: ciclo de purga fallo (%s)", exc)
        try:
            await asyncio.sleep(intervalo_s)
        except asyncio.CancelledError:
            break
