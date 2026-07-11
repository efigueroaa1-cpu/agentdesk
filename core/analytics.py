"""
core/analytics.py — Motor Analítico de Curva S (Earned Value Management).

Combina datos del Motor Gantt (Sprint 6) y Motor Financiero (Sprint 5) para
calcular las tres curvas del análisis de Valor Ganado:

  PV  (Planned Value / BCWS): valor presupuestado del trabajo planificado.
  EV  (Earned Value / BCWP):  valor presupuestado del trabajo realizado.
  AC  (Actual Cost / ACWP):   costo real del trabajo realizado.

KPIs derivados:
  SPI  = EV / PV     (Schedule Performance Index; < 1 → atrasado)
  CPI  = EV / AC     (Cost Performance Index;     < 1 → sobre costo)
  SV   = EV - PV     (Schedule Variance; negativo → atraso)
  CV   = EV - AC     (Cost Variance;     negativo → sobre costo)
  EAC  = BAC / CPI   (Estimate at Completion)
  VAC  = BAC - EAC   (Variance at Completion)

Umbrales para notificaciones proactivas:
  CRITICO: SPI < 0.80 O CPI < 0.80
  ALTO:    SPI < 0.90 O CPI < 0.90

El cálculo se ejecuta en el backend (hilo de uvicorn) para no cargar el hilo
de UI de React. Los resultados se emiten vía WebSocket como:
  { tipo: "curva_s_actualizada", proyecto_id, curva, kpis, alerta }

Requisito de ingeniería Sprint 8.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Umbrales de alerta ─────────────────────────────────────────────────────────
UMBRAL_CRITICO = 0.80
UMBRAL_ALTO    = 0.90


class PuntoSCurva:
    """Un punto en el tiempo de la Curva S."""
    __slots__ = ("fecha", "pv", "ev", "ac", "pv_acum", "ev_acum", "ac_acum")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def to_dict(self) -> dict:
        return {s: getattr(self, s, 0) for s in self.__slots__}


class MotorAnalitica:
    """Calcula la Curva S (EVM) a partir de datos Gantt + Finanzas."""

    # ── Presupuesto por tarea ──────────────────────────────────────────────────

    def _bac_proyecto(self, proyecto_id: str) -> float:
        """
        BAC (Budget at Completion) total del proyecto.
        Intenta obtenerlo del análisis financiero del agente o usa heurística
        basada en la duración total de las tareas.
        """
        try:
            from core.finance import motor_financiero
            from core.gantt  import motor_gantt

            proyecto = motor_gantt.obtener_proyecto(proyecto_id)
            tareas   = proyecto.get("tareas", [])

            # Si hay agente con datos financieros, usar egresos como BAC
            agentes  = {t.get("agente_id") for t in tareas if t.get("agente_id")}
            for agente_id in agentes:
                hist = motor_financiero.historico(agente_id, n=1)
                if hist:
                    flujo = hist[0].get("flujo", {})
                    if flujo.get("egresos", 0) > 0:
                        return float(flujo["egresos"])
        except Exception:
            pass

        # Heurística: $500 USD/día × duración total planificada del proyecto
        try:
            from core.gantt import motor_gantt
            p = motor_gantt.obtener_proyecto(proyecto_id)
            dur_total = sum(t.get("duracion_dias", 0) for t in p.get("tareas", []))
            return max(1000.0, dur_total * 500.0)
        except Exception:
            return 10_000.0

    # ── Costo real acumulado ───────────────────────────────────────────────────

    def _ac_historico(self, proyecto_id: str) -> list[tuple[datetime, float]]:
        """
        Devuelve lista de (fecha, costo_acumulado) desde el histórico financiero.
        Si no hay datos, devuelve lista vacía y el cálculo usará AC ≈ EV (CPI=1).
        """
        try:
            from core.database import AnalisisFinanciero, get_session
            from core.gantt    import motor_gantt

            proyecto  = motor_gantt.obtener_proyecto(proyecto_id)
            agentes   = {t.get("agente_id") for t in proyecto.get("tareas", []) if t.get("agente_id")}

            puntos: list[tuple[datetime, float]] = []
            with get_session() as s:
                for agente_id in agentes:
                    filas = (
                        s.query(AnalisisFinanciero)
                        .filter(AnalisisFinanciero.agente_id == agente_id)
                        .order_by(AnalisisFinanciero.ts.asc())
                        .all()
                    )
                    acum = 0.0
                    for f in filas:
                        # egresos del flujo como costo real incremental
                        flujo  = __import__("json").loads(f.flujo_json or "{}")
                        egreso = abs(flujo.get("egresos", 0))
                        acum  += egreso
                        ts     = f.ts or datetime.utcnow()
                        puntos.append((ts, acum))
            puntos.sort(key=lambda x: x[0])
            return puntos
        except Exception as e:
            logger.debug("_ac_historico: %s", e)
            return []

    # ── Línea de tiempo del proyecto ───────────────────────────────────────────

    def _timeline(self, tareas: list[dict]) -> list[datetime]:
        """
        Genera una lista semanal de fechas desde el inicio hasta max(hoy, fin_plan).
        """
        if not tareas:
            return []

        fechas_inicio = [t["inicio_plan"] for t in tareas if t.get("inicio_plan")]
        fechas_fin    = [t["fin_plan"]    for t in tareas if t.get("fin_plan")]
        if not fechas_inicio:
            return []

        t0 = datetime.fromisoformat(min(fechas_inicio)[:19])
        t1 = datetime.fromisoformat(max(fechas_fin)[:19])
        t1 = max(t1, datetime.utcnow())

        semanas: list[datetime] = []
        cur = t0
        while cur <= t1 + timedelta(days=7):
            semanas.append(cur)
            cur += timedelta(weeks=1)
        return semanas

    # ── Valor ganado por tarea en una fecha ────────────────────────────────────

    @staticmethod
    def _pct_planificado(tarea: dict, en_fecha: datetime) -> float:
        """% planificado de completitud de la tarea en `en_fecha`."""
        try:
            t0 = datetime.fromisoformat(tarea["inicio_plan"][:19])
            t1 = datetime.fromisoformat(tarea["fin_plan"][:19])
        except (KeyError, ValueError):
            return 0.0
        if en_fecha <= t0:
            return 0.0
        if en_fecha >= t1:
            return 100.0
        total = (t1 - t0).total_seconds()
        return ((en_fecha - t0).total_seconds() / total * 100) if total > 0 else 100.0

    # ── Cálculo principal ──────────────────────────────────────────────────────

    def calcular_curva_s(self, proyecto_id: str) -> dict:
        """
        Calcula la Curva S completa del proyecto y retorna:
          curva  — lista de puntos (fecha, pv, ev, ac, pv_acum, ev_acum, ac_acum)
          kpis   — SPI, CPI, SV, CV, EAC, VAC, BAC
          alerta — None | "ALTO" | "CRITICO"
        """
        try:
            from core.gantt import motor_gantt
            proyecto = motor_gantt.obtener_proyecto(proyecto_id)
        except Exception as e:
            logger.error("analytics: no se pudo obtener proyecto '%s': %s", proyecto_id, e)
            return {"proyecto_id": proyecto_id, "curva": [], "kpis": {}, "alerta": None,
                    "error": str(e)}

        tareas = proyecto.get("tareas", [])
        if not tareas:
            return {"proyecto_id": proyecto_id, "curva": [], "kpis": {}, "alerta": None}

        bac      = self._bac_proyecto(proyecto_id)
        timeline = self._timeline(tareas)
        if not timeline:
            return {"proyecto_id": proyecto_id, "curva": [], "kpis": {}, "alerta": None}

        # Peso de cada tarea por duración (proporcional al BAC)
        dur_total = sum(t.get("duracion_dias", 1) for t in tareas) or 1
        pesos     = {t["id"]: t.get("duracion_dias", 1) / dur_total for t in tareas}

        # Datos de costo real histórico
        ac_hist = self._ac_historico(proyecto_id)

        def _ac_en_fecha(fecha: datetime) -> float:
            """Interpolación lineal del AC real en `fecha`."""
            if not ac_hist:
                return 0.0
            anteriores = [(f, v) for f, v in ac_hist if f <= fecha]
            if not anteriores:
                return 0.0
            return anteriores[-1][1]

        # Generar puntos
        puntos:    list[dict]  = []
        pv_acum    = 0.0
        ev_acum    = 0.0
        ac_acum    = 0.0
        hoy        = datetime.utcnow()

        for semana in timeline:
            pv_sem = 0.0
            ev_sem = 0.0
            for t in tareas:
                peso    = pesos.get(t["id"], 0)
                valor   = peso * bac
                pv_sem += valor * (self._pct_planificado(t, semana) / 100.0)
                ev_sem += valor * ((t.get("pct_completado", 0) or 0.0) / 100.0)

            # AC: si tenemos datos reales los usamos; si no, aproximamos ac ≈ ev
            ac_real = _ac_en_fecha(semana) if ac_hist else ev_sem

            pv_acum  = pv_sem          # pv_sem ya es el acumulado hasta esa semana
            ev_acum  = ev_sem          # ídem
            ac_acum  = ac_real

            puntos.append({
                "fecha":   semana.strftime("%Y-%m-%d"),
                "es_futuro": semana > hoy,
                # Diferencias periódicas (semana a semana)
                "pv":      round(pv_sem - (puntos[-1]["pv_acum"] if puntos else 0), 2),
                "ev":      round(ev_sem - (puntos[-1]["ev_acum"] if puntos else 0), 2),
                "ac":      round(ac_real - (puntos[-1]["ac_acum"] if puntos else 0), 2),
                # Acumulados (para la Curva S real)
                "pv_acum": round(pv_acum, 2),
                "ev_acum": round(ev_acum, 2),
                "ac_acum": round(ac_acum, 2),
            })

        # KPIs al día de hoy (último punto pasado)
        puntos_pasados = [p for p in puntos if not p["es_futuro"]]
        ultimo  = puntos_pasados[-1] if puntos_pasados else puntos[0] if puntos else {}

        pv_hoy  = ultimo.get("pv_acum", 0) or 0.001
        ev_hoy  = ultimo.get("ev_acum", 0) or 0.0
        ac_hoy  = ultimo.get("ac_acum", 0) or 0.001

        spi  = round(ev_hoy / pv_hoy, 3) if pv_hoy else 1.0
        cpi  = round(ev_hoy / ac_hoy, 3) if ac_hoy else 1.0
        sv   = round(ev_hoy - pv_hoy, 2)
        cv   = round(ev_hoy - ac_hoy, 2)
        eac  = round(bac / cpi, 2) if cpi != 0 else bac
        vac  = round(bac - eac, 2)

        # Nivel de alerta
        alerta: str | None = None
        if spi < UMBRAL_CRITICO or cpi < UMBRAL_CRITICO:
            alerta = "CRITICO"
        elif spi < UMBRAL_ALTO or cpi < UMBRAL_ALTO:
            alerta = "ALTO"

        resultado = {
            "proyecto_id": proyecto_id,
            "generado_en": datetime.utcnow().isoformat(),
            "curva":       puntos,
            "kpis": {
                "bac":  round(bac, 2),
                "pv":   round(pv_hoy, 2),
                "ev":   round(ev_hoy, 2),
                "ac":   round(ac_hoy, 2),
                "spi":  spi,
                "cpi":  cpi,
                "sv":   sv,
                "cv":   cv,
                "eac":  eac,
                "vac":  vac,
                "pct_completado_global": proyecto.get("resumen", {}).get("pct_avance", 0),
            },
            "alerta": alerta,
        }

        if alerta:
            logger.warning(
                "analytics: proyecto '%s' con desvío %s — SPI=%.2f CPI=%.2f",
                proyecto_id, alerta, spi, cpi,
            )

        return resultado


# ── Singleton ──────────────────────────────────────────────────────────────────
motor_analitica = MotorAnalitica()
