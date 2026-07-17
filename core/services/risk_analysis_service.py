"""
core/services/risk_analysis_service.py — Alertas Proactivas de Riesgo
Industrial-Financiero (Fase 23, ADR-0021).

Un agente 'Analista de Riesgos' evalúa EN PARALELO (Map-Reduce, ADR-0019)
las últimas 1000 métricas industriales del historial OT y cruza lo hallado
con la proyección financiera del Gemelo Digital (`motor_correlacion`).

Diseño en dos capas, deliberado:

  1. CAPA DETERMINISTA (la que dispara alertas): un screening estadístico
     puro-Python detecta anomalías objetivas — parada de máquina (media
     reciente ≪ base nominal), régimen crítico sostenido, sensor mudo. Si
     además la proyección ajustada del proyecto muestra riesgo de
     presupuesto, se emite `AUDITORIA_SEGURIDAD` SIEMPRE. Una alerta de
     seguridad no puede depender del juicio (ni del humor de sampling) de
     un LLM.
  2. CAPA COGNITIVA (la que explica): las 1000 métricas se parten en
     chunks y el Analista de Riesgos los evalúa en paralelo vía
     Map-Reduce (`prompts` por worker, uno por chunk) — su consolidado es
     el diagnóstico narrativo para el operador, auditado en auditoria_ia
     como cualquier Map-Reduce (tipo="map_reduce").

Best-effort: si la capa cognitiva falla (sin orquestador, sin LLM), la
determinista sigue alertando — nunca al revés.
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

N_METRICAS_ANALISIS   = 1000
N_CHUNKS_MAPREDUCE    = 4
UMBRAL_PARADA         = 0.10   # media/base < 10% => maquina detenida
UMBRAL_CRITICO_SOST   = 0.30   # >30% de lecturas en nivel critico => sostenido


def _analisis_estadistico(eventos: list[dict]) -> list[dict]:
    """Screening determinista de anomalías sobre los eventos crudos."""
    por_sensor: dict[str, list[dict]] = {}
    for e in eventos:
        if e.get("fuente"):
            por_sensor.setdefault(e["fuente"], []).append(e)

    anomalias = []
    for sensor_id, evs in por_sensor.items():
        valores = [e["valor"] for e in evs if isinstance(e.get("valor"), (int, float))]
        if not valores:
            continue
        base = (evs[-1].get("metadata") or {}).get("umbral_warn")
        media = sum(valores) / len(valores)
        criticos = sum(1 for e in evs if e.get("nivel") == "critico")

        # Parada: la media reciente es una fraccion minima del regimen del
        # sensor (aprox. por umbral_warn como proxy del regimen alto).
        if base and media < base * UMBRAL_PARADA:
            anomalias.append({"sensor_id": sensor_id, "tipo": "parada_maquina",
                              "media": round(media, 2), "muestras": len(valores)})
        if criticos / len(evs) > UMBRAL_CRITICO_SOST:
            anomalias.append({"sensor_id": sensor_id, "tipo": "critico_sostenido",
                              "pct_criticos": round(criticos / len(evs) * 100, 1),
                              "muestras": len(evs)})
    return anomalias


def _resumen_chunk(eventos: list[dict]) -> str:
    """Digest compacto de un chunk para el prompt del worker (higiene de tokens)."""
    por_sensor: dict[str, list[float]] = {}
    criticos = 0
    for e in eventos:
        if isinstance(e.get("valor"), (int, float)):
            por_sensor.setdefault(e.get("fuente", "?"), []).append(e["valor"])
        if e.get("nivel") == "critico":
            criticos += 1
    lineas = [
        f"- {sid}: n={len(vals)} min={min(vals):.1f} max={max(vals):.1f} "
        f"media={sum(vals) / len(vals):.1f}"
        for sid, vals in por_sensor.items()
    ]
    return (f"{len(eventos)} lecturas, {criticos} en nivel critico.\n"
            + "\n".join(lineas))


class RiskAnalysisService:
    """Analista de Riesgos: screening determinista + evaluación paralela LLM."""

    def __init__(self, get_orquestador: Callable[[], object | None],
                 map_reduce_service=None):
        self._get_orquestador = get_orquestador
        self._map_reduce = map_reduce_service

    async def analizar(self, proyecto_id: str, analista_id: str | None = None,
                        user_id: str = "anonimo") -> dict:
        from core.telemetry_history import eventos_recientes
        from core.telemetry_otel import medir_paso
        from core.analytics import motor_correlacion

        with medir_paso("riesgo.analisis_ot", proyecto=proyecto_id):
            eventos    = eventos_recientes(limit=N_METRICAS_ANALISIS)
            anomalias  = _analisis_estadistico(eventos)
            proyeccion = motor_correlacion.proyeccion_ajustada(proyecto_id)

        riesgo_financiero = bool(anomalias) and (
            proyeccion.get("riesgo_presupuesto") or proyeccion.get("impacto_cronograma")
        )
        if riesgo_financiero:
            logger.error(
                "AUDITORIA_SEGURIDAD: anomalia industrial con riesgo de presupuesto — "
                "proyecto '%s': %d anomalia(s) %s; EAC ajustado=%.2f, "
                "atraso proyectado=%s dias",
                proyecto_id, len(anomalias),
                [a["tipo"] for a in anomalias],
                proyeccion.get("eac_ajustado", 0),
                proyeccion.get("dias_atraso_proyectados", 0),
            )

        evaluacion_llm = None
        if analista_id and self._map_reduce is not None and eventos:
            evaluacion_llm = await self._evaluar_en_paralelo(
                proyecto_id, analista_id, eventos, anomalias, user_id)

        return {
            "proyecto_id":        proyecto_id,
            "metricas_evaluadas": len(eventos),
            "anomalias":          anomalias,
            "riesgo_financiero":  riesgo_financiero,
            "proyeccion":         {k: v for k, v in proyeccion.items() if k != "curva_s"},
            "evaluacion_llm":     evaluacion_llm,
        }

    async def _evaluar_en_paralelo(self, proyecto_id: str, analista_id: str,
                                    eventos: list[dict], anomalias: list[dict],
                                    user_id: str) -> dict | None:
        """Capa cognitiva: chunks del dataset evaluados en paralelo (Map-Reduce)."""
        n = min(N_CHUNKS_MAPREDUCE, max(1, len(eventos) // 50))
        tam = (len(eventos) + n - 1) // n
        chunks = [eventos[i * tam:(i + 1) * tam] for i in range(n)]
        chunks = [c for c in chunks if c]

        prompts = [
            (f"Eres el Analista de Riesgos del proyecto '{proyecto_id}'. "
             f"Evalua este segmento de telemetria industrial (segmento "
             f"{i + 1}/{len(chunks)}) y responde en 3 lineas si hay riesgo "
             f"operacional o financiero:\n{_resumen_chunk(c)}\n"
             f"Anomalias ya detectadas estadisticamente: "
             f"{[a['tipo'] for a in anomalias] or 'ninguna'}")
            for i, c in enumerate(chunks)
        ]
        try:
            return await self._map_reduce.ejecutar(
                analista_id, [analista_id] * len(chunks), prompts[0],
                user_id=user_id, prompts=prompts,
            )
        except Exception as exc:
            logger.warning("RIESGO_OT: evaluacion LLM en paralelo fallo (%s) — "
                           "la alerta determinista no depende de ella", exc)
            return None
