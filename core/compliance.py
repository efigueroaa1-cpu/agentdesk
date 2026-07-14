"""
core/compliance.py — Motor de Auditoría de Cumplimiento.

Fuentes de datos:
  1. agentdesk.db → tabla guardrail_eventos  (inserts desde api.py WebSocketLogHandler)
  2. sistema.log  → fallback si la DB no tiene datos (parseo JSON línea a línea)

Self-healing: si sistema.log supera el límite lo rota antes del análisis.

Salidas:
  - reporte_cumplimiento()  → dict con resumen, alertas y sugerencias de temperatura
  - certificado_seguridad() → bool + justificación
"""

from __future__ import annotations

import json
from core.timeutil import utcnow
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Umbrales ───────────────────────────────────────────────────────────────────
UMBRAL_ALERTAS_ALTO  = 5    # N abortos → nivel ALTO
UMBRAL_ALERTAS_MEDIO = 2    # N abortos → nivel MEDIO
AJUSTE_TEMPERATURA   = 0.1  # reducir temp en este delta cuando hay muchas alucinaciones
TEMP_MINIMA          = 0.05
MAX_LINEAS_LOG       = 3000  # máx de líneas a leer del log (self-healing activa antes)


class MotorCompliance:
    """Analiza guardrails y emite reportes de cumplimiento con sugerencias."""

    # ── Fuente de datos ────────────────────────────────────────────────────────

    def _eventos_db(self, dias: int = 30) -> list[dict]:
        """Lee guardrail_eventos de la DB para los últimos `dias` días."""
        try:
            from core.database import GuardrailEvento, get_session
            desde = utcnow() - timedelta(days=dias)
            with get_session() as s:
                filas = (
                    s.query(GuardrailEvento)
                    .filter(GuardrailEvento.ts >= desde)
                    .order_by(GuardrailEvento.ts.desc())
                    .limit(2000)
                    .all()
                )
                return [f.to_dict() for f in filas]
        except Exception as e:
            logger.warning("compliance: no se pudo leer DB — %s", e)
            return []

    def _eventos_log(self, dias: int = 30) -> list[dict]:
        """
        Fallback: parsea sistema.log línea a línea.
        Self-healing: rota el log si es demasiado grande antes de leerlo.
        """
        from core.log_config import rotar_log_si_necesario
        from core.path_manager import data_path

        ruta = data_path("logs/sistema.log")
        if not Path(ruta).exists():
            return []

        # Self-healing preventivo
        rotado = rotar_log_si_necesario(ruta)
        if rotado:
            logger.info("compliance: log rotado antes del análisis de métricas")

        eventos: list[dict] = []
        desde = utcnow() - timedelta(days=dias)

        try:
            lineas = Path(ruta).read_text(encoding="utf-8", errors="replace").splitlines()
            # Tomar las últimas MAX_LINEAS_LOG líneas para no saturar memoria
            for linea in lineas[-MAX_LINEAS_LOG:]:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    obj = json.loads(linea)
                except json.JSONDecodeError:
                    continue

                if obj.get("status") != "abortado":
                    continue

                ts_str = obj.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str[:19])
                except ValueError:
                    ts = utcnow()

                if ts < desde:
                    continue

                eventos.append({
                    "agente_id": obj.get("agente", "desconocido"),
                    "guardrail": obj.get("filtro",  "desconocido"),
                    "motivo":    obj.get("motivo",  obj.get("message", "")),
                    "ts":        ts.isoformat(),
                })
        except OSError as e:
            logger.warning("compliance: no se pudo leer sistema.log — %s", e)

        return eventos

    def _obtener_eventos(self, dias: int = 30) -> list[dict]:
        """Prioriza DB; usa log como fallback si DB está vacía."""
        eventos = self._eventos_db(dias)
        if not eventos:
            eventos = self._eventos_log(dias)
        return eventos

    # ── Análisis ────────────────────────────────────────────────────────────────

    def reporte_cumplimiento(
        self,
        agente_id: str | None = None,
        dias: int = 30,
    ) -> dict:
        """
        Genera el reporte de auditoría de cumplimiento.

        Retorna:
          resumen          — conteo total de abortos por guardrail
          por_agente       — conteo de abortos agrupado por agente
          alertas          — agentes con nivel ALTO/MEDIO de incidencias
          sugerencias_temp — ajustes de temperatura recomendados
          certificado      — bool: el sistema operó sin patrones críticos
          periodo          — rango de fechas analizado
        """
        eventos = self._obtener_eventos(dias)

        if agente_id:
            eventos = [e for e in eventos if e["agente_id"] == agente_id]

        # ── Conteos ────────────────────────────────────────────────────────────
        total = len(eventos)
        por_guardrail: Counter = Counter(e["guardrail"] for e in eventos)
        por_agente:    dict[str, Counter] = defaultdict(Counter)

        for e in eventos:
            por_agente[e["agente_id"]][e["guardrail"]] += 1

        # ── Alertas por agente ─────────────────────────────────────────────────
        alertas: list[dict] = []
        for ag, guardrailes in por_agente.items():
            n_total = sum(guardrailes.values())
            nivel   = (
                "ALTO"   if n_total >= UMBRAL_ALERTAS_ALTO  else
                "MEDIO"  if n_total >= UMBRAL_ALERTAS_MEDIO else
                "BAJO"
            )
            alertas.append({
                "agente_id":  ag,
                "total_abortos": n_total,
                "nivel":      nivel,
                "guardrails": dict(guardrailes),
            })

        alertas.sort(key=lambda a: a["total_abortos"], reverse=True)

        # ── Sugerencias de temperatura ─────────────────────────────────────────
        sugerencias: list[dict] = []
        try:
            from core.config_loader import load_config
            config = load_config()

            for ag_cfg in config.get("agents", []):
                aid  = ag_cfg.get("id", "")
                temp_actual = ag_cfg.get("temperatura", 0.7)
                n_abortos   = sum(por_agente.get(aid, Counter()).values())

                # Muchos abortos de GroundingGuard → alucinaciones → bajar temp
                n_grounding = por_agente.get(aid, Counter()).get("GroundingGuard", 0)

                if n_grounding >= UMBRAL_ALERTAS_MEDIO:
                    nueva_temp = round(max(TEMP_MINIMA, temp_actual - AJUSTE_TEMPERATURA), 2)
                    sugerencias.append({
                        "agente_id":   aid,
                        "agente_nombre": ag_cfg.get("nombre", aid),
                        "temp_actual": temp_actual,
                        "temp_sugerida": nueva_temp,
                        "razon": (
                            f"{n_grounding} abortos por GroundingGuard en {dias} días. "
                            f"Reducir temperatura {temp_actual} → {nueva_temp} "
                            "para disminuir alucinaciones."
                        ),
                        "accion": f"RELOAD_CONFIG agente_id={aid} temperatura={nueva_temp}",
                    })
        except Exception as e:
            logger.warning("compliance: no se pudo leer config.json — %s", e)

        # ── Certificado de seguridad ───────────────────────────────────────────
        hay_criticos    = any(a["nivel"] == "ALTO" for a in alertas)
        hay_recursion   = por_guardrail.get("RecursionGuard", 0) > 3
        certificado     = not hay_criticos and not hay_recursion
        justificacion   = (
            "Sistema operando dentro de los parámetros de seguridad."
            if certificado else
            "Se detectaron patrones de riesgo: " + (
                "múltiples abortos de alto volumen" if hay_criticos else ""
            ) + (
                "; loops de recursión detectados" if hay_recursion else ""
            ) + ". Ver sugerencias de temperatura."
        )

        return {
            "periodo":           f"Últimos {dias} días",
            "total_eventos":     total,
            "por_guardrail":     dict(por_guardrail),
            "por_agente":        {k: dict(v) for k, v in por_agente.items()},
            "alertas":           alertas,
            "sugerencias_temp":  sugerencias,
            "certificado":       certificado,
            "justificacion":     justificacion,
            "generado_en":       utcnow().isoformat(),
        }

    def registrar_evento(self, agente_id: str, guardrail: str, motivo: str = "") -> None:
        """
        Persiste un evento de abort en guardrail_eventos (DB).
        Llamado desde api.py WebSocketLogHandler cuando status='abortado'.
        """
        try:
            from core.database import GuardrailEvento, get_session
            with get_session() as s:
                s.add(GuardrailEvento(
                    agente_id=agente_id,
                    guardrail=guardrail,
                    motivo=motivo[:500] if motivo else "",
                ))
                s.commit()
        except Exception as e:
            logger.warning("compliance.registrar_evento: %s", e)


# ── Singleton ──────────────────────────────────────────────────────────────────
motor_compliance = MotorCompliance()
