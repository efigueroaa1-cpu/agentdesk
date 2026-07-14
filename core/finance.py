"""
core/finance.py — Motor de Inteligencia Financiera AgentDesk.

Responsabilidades:
  - Obtener indicadores macro Chile en tiempo real (UF, Dólar, IPC) desde mindicador.cl
  - Calcular flujo de caja y proyecciones a N meses
  - Persistir análisis en agentdesk.db (tabla analisis_financiero)
  - Validar toda entrada/salida con Pydantic v2 (rollback automático si falla)

Integración:
  core.tools._consultar_indicadores_chile() — fuente de datos
  core.database.AnalisisFinanciero          — persistencia
  core.schemas.PresupuestoConfig            — validación de entrada
"""

from __future__ import annotations

import asyncio
from core.timeutil import utcnow
import json
import logging
from datetime import datetime
from statistics import mean, stdev

from pydantic import ValidationError

from core.schemas import (
    IndicadorChile,
    PresupuestoConfig,
    FlujoCajaProyeccion,
)

logger = logging.getLogger(__name__)

# ── Tasa de crecimiento por defecto para proyecciones (0.5% mensual) ──────────
_TASA_CRECIMIENTO_DEFAULT = 0.005


class MotorFinanciero:
    """
    Motor de análisis financiero por agente.

    Thread-safety: todas las operaciones de DB usan context managers de SQLAlchemy.
    Las llamadas HTTP son async — no bloquean el event loop.
    """

    # ── Obtención de indicadores macro ─────────────────────────────────────────

    async def obtener_indicadores(self) -> IndicadorChile:
        """
        Consulta UF, Dólar, Euro e IPC del Banco Central (mindicador.cl).

        Si la API falla, lanza RuntimeError con fallback informativo
        en lugar de devolver valores ficticios silenciosos.
        """
        try:
            from core.web_monitor import _get
            data = await asyncio.wait_for(
                _get("https://mindicador.cl/api"),
                timeout=10.0,
            )
            if not isinstance(data, dict):
                raise ValueError("Respuesta inesperada del Banco Central")

            indicadores = IndicadorChile(
                uf=float(data.get("uf",    {}).get("valor", 0)),
                dolar=float(data.get("dolar", {}).get("valor", 0)),
                euro=float(data.get("euro",  {}).get("valor", 0)),
                ipc=float(data.get("ipc",   {}).get("valor", 0)),
                timestamp=utcnow(),
            )
            logger.info(
                "Indicadores Chile obtenidos: UF=%.2f Dólar=%.2f",
                indicadores.uf, indicadores.dolar,
            )
            return indicadores

        except ValidationError as e:
            logger.error("Validación Pydantic falló en indicadores: %s", e)
            raise RuntimeError(f"Indicadores inválidos del Banco Central: {e}") from e
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("No se pudo conectar al Banco Central: %s", e)
            raise RuntimeError(
                "Banco Central no disponible. Verifica conectividad o reintenta."
            ) from e

    # ── Cálculo de flujo de caja ───────────────────────────────────────────────

    def calcular_flujo_caja(self, presupuesto: PresupuestoConfig) -> dict:
        """
        Calcula el flujo de caja actual a partir del presupuesto validado.

        Retorna:
          ingresos, egresos, flujo_neto, margen_pct, items
        """
        ingresos = presupuesto.total_ingresos
        egresos  = presupuesto.total_egresos
        neto     = presupuesto.flujo_neto
        margen   = (neto / ingresos * 100) if ingresos > 0 else 0.0

        return {
            "ingresos":   ingresos,
            "egresos":    egresos,
            "flujo_neto": neto,
            "margen_pct": round(margen, 2),
            "items":      [i.model_dump() for i in presupuesto.items],
            "periodo":    presupuesto.periodo,
            "moneda":     presupuesto.moneda,
        }

    # ── Proyección a N períodos ────────────────────────────────────────────────

    def proyectar(
        self,
        presupuesto: PresupuestoConfig,
        periodos: int = 6,
        tasa_crecimiento: float | None = None,
    ) -> list[FlujoCajaProyeccion]:
        """
        Proyecta el flujo de caja a `periodos` meses futuros.

        Asume crecimiento lineal constante sobre ingresos y egresos.
        Si `tasa_crecimiento` es None, se usa el default global (0.5% mensual).
        Retorna lista de `FlujoCajaProyeccion` validada por Pydantic.
        """
        if periodos < 1 or periodos > 60:
            raise ValueError(f"periodos debe estar entre 1 y 60, recibido: {periodos}")

        tasa = tasa_crecimiento if tasa_crecimiento is not None else _TASA_CRECIMIENTO_DEFAULT
        base_ingresos = presupuesto.total_ingresos
        base_egresos  = presupuesto.total_egresos

        proyeccion: list[FlujoCajaProyeccion] = []
        acumulado = 0.0

        for mes in range(1, periodos + 1):
            factor   = (1 + tasa) ** mes
            ing_proy = round(base_ingresos * factor, 2)
            egr_proy = round(base_egresos  * factor, 2)
            neto_proy = round(ing_proy - egr_proy, 2)
            acumulado = round(acumulado + neto_proy, 2)

            try:
                punto = FlujoCajaProyeccion(
                    mes=mes,
                    ingreso_proy=ing_proy,
                    egreso_proy=egr_proy,
                    flujo_neto_proy=neto_proy,
                    acumulado=acumulado,
                )
                proyeccion.append(punto)
            except ValidationError as e:
                logger.error("Error de validación en proyección mes %d: %s", mes, e)
                break  # corta la proyección en lugar de propagar datos inválidos

        return proyeccion

    # ── Persistencia ───────────────────────────────────────────────────────────

    async def analizar_y_persistir(
        self,
        agente_id: str,
        presupuesto: PresupuestoConfig,
        periodos: int = 6,
    ) -> dict:
        """
        Orquesta: obtener indicadores → calcular flujo → proyectar → guardar en DB.

        En caso de fallo de cualquier etapa, no persiste datos parciales
        (la sesión SQLAlchemy se descarta si ocurre excepción).

        Retorna el análisis completo como dict serializable.
        """
        from core.database import AnalisisFinanciero, get_session

        # 1. Indicadores reales
        try:
            indicadores = await self.obtener_indicadores()
        except RuntimeError as e:
            logger.warning("Usando indicadores sin conexión: %s", e)
            indicadores = None

        # 2. Flujo de caja
        flujo = self.calcular_flujo_caja(presupuesto)

        # 3. Proyección
        proyeccion = self.proyectar(presupuesto, periodos=periodos)

        # 4. Persistencia atómica
        analisis_dict = {
            "agente_id":   agente_id,
            "indicadores": indicadores.model_dump(mode="json") if indicadores else None,
            "presupuesto": presupuesto.model_dump(mode="json"),
            "flujo":       flujo,
            "proyeccion":  [p.model_dump() for p in proyeccion],
            "ts":          utcnow().isoformat(),
        }

        try:
            with get_session() as s:
                registro = AnalisisFinanciero(
                    agente_id=agente_id,
                    indicadores_json=json.dumps(analisis_dict["indicadores"] or {}),
                    presupuesto_json=json.dumps(analisis_dict["presupuesto"]),
                    flujo_json=json.dumps(analisis_dict["proyeccion"]),
                    uf_valor=indicadores.uf if indicadores else None,
                    dolar_valor=indicadores.dolar if indicadores else None,
                    flujo_neto=flujo["flujo_neto"],
                )
                s.add(registro)
                s.commit()
                analisis_dict["id"] = registro.id
                logger.info(
                    "Análisis financiero persistido: agente=%s id=%s flujo_neto=%.2f",
                    agente_id, registro.id, flujo["flujo_neto"],
                )
        except Exception as e:
            logger.error("No se pudo persistir análisis financiero: %s", e)
            analisis_dict["error_db"] = str(e)

        return analisis_dict

    # ── Historial ──────────────────────────────────────────────────────────────

    def historico(self, agente_id: str, n: int = 10) -> list[dict]:
        """
        Recupera los últimos N análisis financieros del agente desde la DB.
        """
        from core.database import AnalisisFinanciero, get_session

        try:
            with get_session() as s:
                filas = (
                    s.query(AnalisisFinanciero)
                    .filter(AnalisisFinanciero.agente_id == agente_id)
                    .order_by(AnalisisFinanciero.ts.desc())
                    .limit(max(1, min(n, 100)))
                    .all()
                )
                return [f.to_dict() for f in filas]
        except Exception as e:
            logger.error("Error al consultar historial financiero: %s", e)
            return []

    # ── Estadísticas de tendencia ──────────────────────────────────────────────

    def tendencia_flujo(self, agente_id: str, n: int = 10) -> dict:
        """
        Calcula la tendencia del flujo neto histórico.

        Retorna: promedio, desviacion, tendencia ("mejora"|"empeora"|"estable")
        """
        registros = self.historico(agente_id, n=n)
        flujos = [r["flujo_neto"] for r in registros if r.get("flujo_neto") is not None]

        if len(flujos) < 2:
            return {"tendencia": "sin_datos", "promedio": 0, "desviacion": 0}

        prom = round(mean(flujos), 2)
        desv = round(stdev(flujos), 2) if len(flujos) > 1 else 0.0

        mid  = len(flujos) // 2
        avg1 = mean(flujos[:mid]) if mid else flujos[0]
        avg2 = mean(flujos[mid:])
        diff_pct = (avg2 - avg1) / abs(avg1) * 100 if avg1 != 0 else 0

        if diff_pct > 5:
            tendencia = "mejora"
        elif diff_pct < -5:
            tendencia = "empeora"
        else:
            tendencia = "estable"

        return {
            "tendencia":  tendencia,
            "promedio":   prom,
            "desviacion": desv,
            "diff_pct":   round(diff_pct, 2),
            "n_muestras": len(flujos),
        }


# ── Singleton para uso desde api.py y orchestrator.py ─────────────────────────
motor_financiero = MotorFinanciero()
