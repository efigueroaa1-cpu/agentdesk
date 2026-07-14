"""
core/risk_engine.py — Motor de Análisis de Riesgos.

Correlaciona el avance del Gantt (Sprint 6) con el flujo de caja (Sprint 5)
para detectar desviaciones de cronograma con impacto financiero proyectado.

Algoritmo:
  1. Para cada tarea del proyecto calcula % esperado en base a fecha actual.
  2. Compara con pct_completado real → desvío en días.
  3. Consulta el histórico financiero del agente para obtener costo/día.
  4. Proyecta el impacto monetario de la demora.
  5. Emite alertas ordenadas por severidad.
"""

from __future__ import annotations

import logging
from core.timeutil import utcnow
from datetime import datetime
from typing import Literal

logger = logging.getLogger(__name__)

# ── Umbrales ───────────────────────────────────────────────────────────────────
DESVIACION_CRITICA  = 20.0   # % de desvío → nivel CRITICO
DESVIACION_ALTA     = 10.0   # % de desvío → nivel ALTO
COSTO_DIA_DEFAULT   = 500.0  # USD/día si no hay datos financieros del agente


class AlertaRiesgo:
    __slots__ = ("tarea_id", "tarea_nombre", "agente_id", "pct_esperado",
                 "pct_real", "desviacion", "dias_retraso",
                 "impacto_financiero", "moneda", "nivel", "mensaje")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def to_dict(self) -> dict:
        return {s: getattr(self, s, None) for s in self.__slots__}


class MotorRiesgo:
    """Detecta desviaciones Gantt→Finanzas y genera alertas de impacto."""

    # ── Cálculo de % esperado ──────────────────────────────────────────────────

    @staticmethod
    def _pct_esperado(inicio_plan: str | None, fin_plan: str | None) -> float:
        """% teórico que debería estar completado hoy según el cronograma."""
        if not inicio_plan or not fin_plan:
            return 0.0
        try:
            t0  = datetime.fromisoformat(inicio_plan[:19])
            t1  = datetime.fromisoformat(fin_plan[:19])
            hoy = utcnow()
            if hoy <= t0:
                return 0.0
            if hoy >= t1:
                return 100.0
            total = (t1 - t0).total_seconds()
            if total <= 0:
                return 100.0
            return round((hoy - t0).total_seconds() / total * 100, 1)
        except ValueError:
            return 0.0

    # ── Costo diario del agente (desde histórico financiero) ───────────────────

    def _costo_dia(self, agente_id: str) -> tuple[float, str]:
        """
        Devuelve (costo_por_dia, moneda) estimado del agente.
        Usa egresos promedio / duración_promedio de sus tareas Gantt como proxy.
        Fallback: COSTO_DIA_DEFAULT USD.
        """
        try:
            from core.finance import motor_financiero
            hist = motor_financiero.historico(agente_id, n=5)
            if hist:
                egresos = [
                    h.get("flujo", {}).get("egresos", 0)
                    for h in hist
                    if isinstance(h.get("flujo"), dict)
                ]
                moneda  = hist[0].get("flujo", {}).get("moneda", "USD") if hist else "USD"
                if egresos:
                    prom_egreso = sum(egresos) / len(egresos)
                    costo_dia   = round(prom_egreso / 30, 2)   # mensual → diario
                    return max(costo_dia, 1.0), moneda
        except Exception:
            pass
        return COSTO_DIA_DEFAULT, "USD"

    # ── Análisis principal ──────────────────────────────────────────────────────

    def analizar_proyecto(self, proyecto_id: str) -> dict:
        """
        Analiza todas las tareas del proyecto y retorna alertas de riesgo
        ordenadas por severidad y desvío financiero.
        """
        try:
            from core.gantt import motor_gantt
            proyecto = motor_gantt.obtener_proyecto(proyecto_id)
        except Exception as e:
            logger.error("risk_engine: no se pudo obtener proyecto '%s': %s", proyecto_id, e)
            return {"proyecto_id": proyecto_id, "alertas": [], "error": str(e)}

        tareas  = proyecto.get("tareas", [])
        alertas: list[AlertaRiesgo] = []

        for t in tareas:
            if t.get("pct_completado", 0) >= 100.0:
                continue   # tarea completada → sin riesgo activo

            esperado   = self._pct_esperado(t.get("inicio_plan"), t.get("fin_plan"))
            real       = t.get("pct_completado", 0.0)
            desviacion = round(esperado - real, 1)

            if desviacion <= 0:
                continue   # adelantado o en tiempo

            # Días de retraso estimados
            duracion_total = t.get("duracion_dias", 1.0)
            dias_retraso   = round(desviacion / 100.0 * duracion_total, 1)

            # Impacto financiero
            agente_id = t.get("agente_id") or ""
            costo_dia, moneda = self._costo_dia(agente_id) if agente_id else (COSTO_DIA_DEFAULT, "USD")
            impacto = round(dias_retraso * costo_dia, 2)

            # Nivel de severidad
            if desviacion >= DESVIACION_CRITICA:
                nivel = "CRITICO"
            elif desviacion >= DESVIACION_ALTA:
                nivel = "ALTO"
            else:
                nivel = "MEDIO"

            mensaje = (
                f"La tarea '{t['nombre']}' lleva {real:.0f}% completada "
                f"cuando debería estar al {esperado:.0f}% "
                f"(desvío {desviacion:.1f}%). "
                f"Retraso estimado: {dias_retraso:.1f} días → "
                f"impacto financiero: ${impacto:,.2f} {moneda}."
            )
            if t.get("en_ruta_critica"):
                mensaje += " ⚠ TAREA EN RUTA CRÍTICA — impacta la fecha de entrega total."

            alertas.append(AlertaRiesgo(
                tarea_id=t["id"],
                tarea_nombre=t["nombre"],
                agente_id=agente_id,
                pct_esperado=esperado,
                pct_real=real,
                desviacion=desviacion,
                dias_retraso=dias_retraso,
                impacto_financiero=impacto,
                moneda=moneda,
                nivel=nivel,
                mensaje=mensaje,
            ))

        # Ordenar: primero crítico, luego por impacto descendente
        _orden = {"CRITICO": 0, "ALTO": 1, "MEDIO": 2}
        alertas.sort(key=lambda a: (_orden[a.nivel], -a.impacto_financiero))

        impacto_total = sum(a.impacto_financiero for a in alertas)
        moneda_total  = alertas[0].moneda if alertas else "USD"

        return {
            "proyecto_id":    proyecto_id,
            "generado_en":    utcnow().isoformat(),
            "tareas_analizadas": len(tareas),
            "alertas_activas":   len(alertas),
            "impacto_total":     round(impacto_total, 2),
            "moneda":            moneda_total,
            "alertas":           [a.to_dict() for a in alertas],
        }

    # ── Salud global del sistema ────────────────────────────────────────────────

    def salud_sistema(self) -> dict:
        """
        Consolida métricas clave para el BI Dashboard (ID 9):
          - gantt:      avance promedio de todos los proyectos
          - finanzas:   tendencia del flujo neto (último agente con datos)
          - compliance: resultado del reporte de cumplimiento
          - alertas:    resumen de riesgo (críticos + altos)
          - score:      puntaje 0-100 calculado como promedio ponderado
        """
        resultado: dict = {
            "generado_en": utcnow().isoformat(),
            "gantt":       {},
            "finanzas":    {},
            "compliance":  {},
            "alertas_criticas": 0,
            "alertas_altas":    0,
            "score":       100,
        }

        # ── Gantt ──────────────────────────────────────────────────────────────
        try:
            from core.gantt import motor_gantt
            proyectos = motor_gantt.listar_proyectos()
            if proyectos:
                avances = [p["resumen"].get("pct_avance", 0) for p in proyectos]
                resultado["gantt"] = {
                    "n_proyectos": len(proyectos),
                    "avance_promedio": round(sum(avances) / len(avances), 1),
                    "proyectos": proyectos,
                }
                # Sumar alertas de todos los proyectos
                for p in proyectos:
                    analisis = self.analizar_proyecto(p["proyecto_id"])
                    for a in analisis.get("alertas", []):
                        if a["nivel"] == "CRITICO":
                            resultado["alertas_criticas"] += 1
                        elif a["nivel"] == "ALTO":
                            resultado["alertas_altas"] += 1
        except Exception as e:
            logger.warning("salud_sistema: gantt error — %s", e)

        # ── Finanzas ───────────────────────────────────────────────────────────
        try:
            from core.database import AnalisisFinanciero, get_session
            with get_session() as s:
                ultimo = (
                    s.query(AnalisisFinanciero)
                    .order_by(AnalisisFinanciero.ts.desc())
                    .first()
                )
                if ultimo:
                    resultado["finanzas"] = {
                        "agente_id":   ultimo.agente_id,
                        "flujo_neto":  ultimo.flujo_neto,
                        "uf_valor":    ultimo.uf_valor,
                        "dolar_valor": ultimo.dolar_valor,
                        "ts":          ultimo.ts.isoformat() if ultimo.ts else None,
                    }
        except Exception as e:
            logger.warning("salud_sistema: finanzas error — %s", e)

        # ── Compliance ─────────────────────────────────────────────────────────
        try:
            from core.compliance import motor_compliance
            rep = motor_compliance.reporte_cumplimiento(dias=7)
            resultado["compliance"] = {
                "certificado":    rep["certificado"],
                "total_eventos":  rep["total_eventos"],
                "alertas_nivel":  [a for a in rep["alertas"] if a["nivel"] != "BAJO"],
            }
        except Exception as e:
            logger.warning("salud_sistema: compliance error — %s", e)

        # ── Score 0-100 ────────────────────────────────────────────────────────
        score = 100
        score -= resultado["alertas_criticas"] * 15
        score -= resultado["alertas_altas"]    * 7
        cert   = resultado.get("compliance", {}).get("certificado", True)
        if not cert:
            score -= 10
        fin_neto = resultado.get("finanzas", {}).get("flujo_neto")
        if fin_neto is not None and fin_neto < 0:
            score -= 10
        resultado["score"] = max(0, min(100, score))

        return resultado


# ── Singleton ──────────────────────────────────────────────────────────────────
motor_riesgo = MotorRiesgo()
