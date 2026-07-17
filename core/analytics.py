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
from core.timeutil import utcnow
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
                        ts     = f.ts or utcnow()
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
        t1 = max(t1, utcnow())

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
        hoy        = utcnow()

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
            "generado_en": utcnow().isoformat(),
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


# ── Gemelo Digital Operativo (Fase 23, ADR-0021) ───────────────────────────────

FACTOR_PARADA          = 0.05   # bajo esto, la produccion se considera DETENIDA
FACTOR_MAXIMO          = 1.25   # sobre-rendimiento acotado (no proyectar milagros)
VENTANA_EVENTOS_FACTOR = 60     # ultimos N eventos por sensor para el factor


class MotorCorrelacionOT:
    """
    Vincula tags de planta (Modbus/OPC-UA/MQTT) con proyectos Gantt y ajusta
    la proyección de la Curva S con el rendimiento REAL de producción.

    La Curva S clásica (MotorAnalitica) solo ve el avance REPORTADO
    (pct_completado cargado a mano en Gantt). Este motor agrega la señal
    física: si los sensores vinculados muestran la línea produciendo a X%
    de su rendimiento nominal, el trabajo restante tomará 1/X veces lo
    planificado — eso adelanta HOY la detección de un atraso que el
    cronograma solo confesaría semanas después.
    """

    def __init__(self):
        # proyecto_id -> [{sensor_id, rendimiento_nominal}]; el rendimiento
        # nominal es el valor del tag a produccion plena (ej. ciclos/min).
        self._vinculos: dict[str, list[dict]] = {}

    def vincular(self, proyecto_id: str, sensor_id: str,
                 rendimiento_nominal: float) -> dict:
        if rendimiento_nominal <= 0:
            raise ValueError("rendimiento_nominal debe ser > 0")
        vinculo = {"sensor_id": sensor_id,
                   "rendimiento_nominal": float(rendimiento_nominal)}
        self._vinculos.setdefault(proyecto_id, []).append(vinculo)
        return vinculo

    def vinculos_de(self, proyecto_id: str) -> list[dict]:
        return list(self._vinculos.get(proyecto_id, []))

    def factor_produccion(self, proyecto_id: str) -> dict:
        """
        Rendimiento real de la planta vs. nominal, en [0, FACTOR_MAXIMO].
        1.0 = produciendo a plan; ~0 = parada de maquina. Sin vinculos o sin
        telemetria: factor 1.0 con detalle explicito (la Curva S clasica
        sigue valiendo tal cual — el Gemelo no inventa datos que no tiene).
        """
        from core.telemetry_history import eventos_recientes
        vinculos = self._vinculos.get(proyecto_id, [])
        if not vinculos:
            return {"factor": 1.0, "sensores": [], "parada_detectada": False,
                    "detalle": "sin vinculos OT"}

        sensores = []
        factores = []
        for v in vinculos:
            eventos = eventos_recientes(limit=VENTANA_EVENTOS_FACTOR,
                                        fuente=v["sensor_id"])
            valores = [e["valor"] for e in eventos
                       if isinstance(e.get("valor"), (int, float))]
            if not valores:
                sensores.append({**v, "factor": None, "muestras": 0})
                continue
            promedio = sum(valores) / len(valores)
            factor   = max(0.0, min(FACTOR_MAXIMO,
                                    promedio / v["rendimiento_nominal"]))
            factores.append(factor)
            sensores.append({**v, "factor": round(factor, 3),
                             "muestras": len(valores)})

        if not factores:
            return {"factor": 1.0, "sensores": sensores, "parada_detectada": False,
                    "detalle": "vinculos sin telemetria reciente"}
        factor_global = round(sum(factores) / len(factores), 3)
        return {"factor": factor_global, "sensores": sensores,
                "parada_detectada": factor_global < FACTOR_PARADA,
                "detalle": f"{len(factores)} sensor(es) con telemetria"}

    def proyeccion_ajustada(self, proyecto_id: str) -> dict:
        """
        Curva S clasica + señal fisica de planta:
          - nueva fecha fin proyectada (trabajo restante / factor real),
          - impacto_cronograma si esa fecha supera el fin planificado,
          - EAC ajustado y riesgo_presupuesto si supera el BAC.
        Emite AUDITORIA_SEGURIDAD ante riesgo financiero — la alerta
        proactiva del criterio de la fase, deterministica (no depende del
        juicio de un LLM para dispararse).
        """
        base       = motor_analitica.calcular_curva_s(proyecto_id)
        produccion = self.factor_produccion(proyecto_id)
        factor     = produccion["factor"]

        try:
            from core.gantt import motor_gantt
            proyecto   = motor_gantt.obtener_proyecto(proyecto_id)
            fines_plan = [t["fin_plan"] for t in proyecto.get("tareas", [])
                          if t.get("fin_plan")]
            fin_plan   = max(fines_plan) if fines_plan else None
        except Exception:
            fin_plan = None

        hoy = utcnow()
        impacto = {"impacto_cronograma": False, "dias_atraso_proyectados": 0,
                   "fin_plan": fin_plan, "fin_proyectado": fin_plan}
        if fin_plan:
            fin_dt          = datetime.fromisoformat(str(fin_plan)[:19])
            dias_restantes  = max(0.0, (fin_dt - hoy).total_seconds() / 86400)
            factor_efectivo = max(factor, FACTOR_PARADA)
            dias_ajustados  = dias_restantes / factor_efectivo
            fin_proyectado  = hoy + timedelta(days=dias_ajustados)
            atraso          = max(0, round(dias_ajustados - dias_restantes))
            impacto = {
                "impacto_cronograma":      fin_proyectado > fin_dt and atraso >= 1,
                "dias_atraso_proyectados": atraso,
                "fin_plan":                fin_dt.strftime("%Y-%m-%d"),
                "fin_proyectado":          fin_proyectado.strftime("%Y-%m-%d"),
            }

        kpis = base.get("kpis", {})
        bac  = kpis.get("bac", 0) or 0
        cpi  = kpis.get("cpi", 1) or 1
        eac_ajustado = round(bac / max(cpi * max(factor, FACTOR_PARADA), 0.01), 2) if bac else 0
        riesgo_presupuesto = bool(bac) and eac_ajustado > bac * 1.05  # >5% sobre BAC

        if riesgo_presupuesto:
            logger.error(
                "AUDITORIA_SEGURIDAD: riesgo financiero por telemetria de planta — "
                "proyecto '%s': factor_produccion=%.2f, EAC ajustado %.2f supera "
                "BAC %.2f (parada=%s, atraso proyectado=%s dias)",
                proyecto_id, factor, eac_ajustado, bac,
                produccion.get("parada_detectada", False),
                impacto["dias_atraso_proyectados"],
            )

        return {
            "proyecto_id":        proyecto_id,
            "curva_s":            base,
            "produccion":         produccion,
            **impacto,
            "eac_ajustado":       eac_ajustado,
            "riesgo_presupuesto": riesgo_presupuesto,
            "spi_fisico":         round((kpis.get("spi", 1) or 1) * factor, 3),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────
motor_analitica   = MotorAnalitica()
motor_correlacion = MotorCorrelacionOT()
