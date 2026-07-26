# -*- coding: utf-8 -*-
"""
core/tools_finance.py — Herramienta financiera (VAN/TIR/TIRM y calcular_financiero).

Extraido de core/tools.py (2026-07-26, Strangler Fig v1.3, incremento 2/N):
matematica financiera pura (solo math + stdlib), sin acoplamiento con el
resto de tools. El dispatcher (core/tools.py) importa _calcular_financiero.
"""
import logging
import math

logger = logging.getLogger(__name__)


def _npv(tasa: float, flujos: list[float]) -> float:
    return sum(f / (1 + tasa) ** t for t, f in enumerate(flujos))

def _irr(flujos: list[float], guess: float = 0.1) -> float | None:
    """Newton-Raphson para TIR. Retorna None si no converge."""
    r = guess
    for _ in range(2000):
        f  = _npv(r, flujos)
        df = sum(-t * v / (1 + r) ** (t + 1) for t, v in enumerate(flujos))
        if df == 0:
            break
        r_new = r - f / df
        if abs(r_new - r) < 1e-8:
            return r_new
        r = r_new
    # Bisección como fallback
    lo, hi = -0.9999, 10.0
    try:
        for _ in range(200):
            mid = (lo + hi) / 2
            if _npv(mid, flujos) > 0:
                lo = mid
            else:
                hi = mid
            if (hi - lo) < 1e-8:
                return (lo + hi) / 2
    except Exception:
        pass
    return None

def _mirr(flujos: list[float], tasa_fin: float, tasa_rein: float) -> float | None:
    n = len(flujos) - 1
    if n <= 0:
        return None
    pv_neg = sum(f / (1 + tasa_fin) ** t for t, f in enumerate(flujos) if f < 0)
    fv_pos = sum(f * (1 + tasa_rein) ** (n - t) for t, f in enumerate(flujos) if f > 0)
    if pv_neg == 0:
        return None
    return (fv_pos / abs(pv_neg)) ** (1 / n) - 1


async def _calcular_financiero(tipo: str, datos: dict) -> str:
    try:
        # ── VAN / TIR / TIRM / Payback ────────────────────────────────────────
        if tipo == "van_tir":
            flujos = [float(x) for x in datos.get("flujos", [])]
            tasa   = float(datos.get("tasa", 0.1))
            t_rein = float(datos.get("tasa_reinversion", tasa))
            if not flujos:
                return "Error: 'flujos' es requerido. Ej: [-1000, 300, 400, 500]"
            n    = len(flujos) - 1
            van  = _npv(tasa, flujos)
            tir  = _irr(flujos)
            tirm = _mirr(flujos, tasa, t_rein)

            # Payback simple
            acum, pb_simple = 0.0, None
            for t, f in enumerate(flujos):
                acum += f
                if acum >= 0 and pb_simple is None:
                    pb_simple = t

            # Payback descontado
            acum_d, pb_desc = 0.0, None
            for t, f in enumerate(flujos):
                acum_d += f / (1 + tasa) ** t
                if acum_d >= 0 and pb_desc is None:
                    pb_desc = t

            lineas = [
                f"ANÁLISIS FINANCIERO DEL PROYECTO ({n} períodos, tasa={tasa*100:.1f}%)",
                "=" * 55,
                f"VAN  (Valor Actual Neto)       : ${van:>14,.0f}   {'✅ >0' if van>0 else '❌ <0'}",
                f"TIR  (Tasa Interna de Retorno) : {tir*100:>13.2f}%   {'✅ >WACC' if tir and tir>tasa else '❌ <WACC'}" if tir is not None else "TIR  : no converge (flujos no permiten solución única)",
                f"TIRM (TIR Modificada)          : {tirm*100:>13.2f}%" if tirm is not None else "TIRM : no calculable",
                f"Payback Simple                 : {pb_simple:>10} período(s)" if pb_simple else "Payback Simple : no se recupera la inversión",
                f"Payback Descontado             : {pb_desc:>10} período(s)" if pb_desc else "Payback Descontado : no se recupera la inversión",
                "",
                "FLUJO DE CAJA ACUMULADO:",
                f"{'Per':>4} | {'Flujo':>12} | {'Acum. Simple':>14} | {'Acum. Desct.':>14}",
                "-" * 48,
            ]
            acum_s, acum_d2 = 0.0, 0.0
            for t, f in enumerate(flujos):
                acum_s  += f
                acum_d2 += f / (1 + tasa) ** t
                lineas.append(f"{t:>4} | {f:>12,.0f} | {acum_s:>14,.0f} | {acum_d2:>14,.0f}")
            lineas.append("")
            lineas.append(f"VEREDICTO: {'✅ PROYECTO VIABLE (VAN>0 y TIR>WACC)' if van>0 and tir and tir>tasa else '❌ PROYECTO NO VIABLE'}")
            return "\n".join(lineas)

        # ── EVM (Earned Value Management) ─────────────────────────────────────
        elif tipo == "evm":
            bac = float(datos.get("bac", 0))
            pv  = float(datos.get("pv",  0))
            ev  = float(datos.get("ev",  0))
            ac  = float(datos.get("ac",  0))
            if not any([bac, pv, ev, ac]):
                return "Error: se requieren bac, pv, ev, ac."
            sv   = ev - pv
            cv   = ev - ac
            spi  = ev / pv  if pv  else None
            cpi  = ev / ac  if ac  else None
            eac  = bac / cpi if cpi else None
            vac  = bac - eac if eac else None
            tcpi = (bac - ev) / (bac - ac) if (bac - ac) else None

            def sem(v, bueno): return "🟢" if bueno else "🔴"
            lineas = [
                "DASHBOARD EVM — CONTROL DEL PROYECTO",
                "=" * 55,
                f"{'Indicador':<35} {'Valor':>12}  {'Estado'}",
                "-" * 55,
                f"{'BAC  (Presupuesto a Completar)':<35} {bac:>12,.0f}",
                f"{'PV   (Valor Planificado)':<35} {pv:>12,.0f}",
                f"{'EV   (Valor Ganado)':<35} {ev:>12,.0f}",
                f"{'AC   (Costo Real)':<35} {ac:>12,.0f}",
                "-" * 55,
                f"{'SV   (Variación Cronograma)':<35} {sv:>12,.0f}  {sem(sv>=0, sv>=0)} {'A tiempo' if sv>=0 else 'ATRASADO'}",
                f"{'CV   (Variación de Costo)':<35} {cv:>12,.0f}  {sem(cv>=0, cv>=0)} {'En presupuesto' if cv>=0 else 'SOBRECOSTO'}",
                f"{'SPI  (Índice Cronograma)':<35} {spi:>12.3f}  {sem(spi>=1, spi and spi>=1)} {'>=1 OK' if spi and spi>=1 else '<1 ATRASADO'}" if spi else f"{'SPI':<35} {'N/D':>12}",
                f"{'CPI  (Índice Costo)':<35} {cpi:>12.3f}  {sem(cpi>=1, cpi and cpi>=1)} {'>=1 OK' if cpi and cpi>=1 else '<1 SOBRECOSTO'}" if cpi else f"{'CPI':<35} {'N/D':>12}",
                f"{'EAC  (Estimado a Completar)':<35} {eac:>12,.0f}" if eac else f"{'EAC':<35} {'N/D':>12}",
                f"{'VAC  (Variación al Completar)':<35} {vac:>12,.0f}  {sem(vac and vac>=0, vac and vac>=0)}" if vac is not None else f"{'VAC':<35} {'N/D':>12}",
                f"{'TCPI (Eficiencia Requerida)':<35} {tcpi:>12.3f}  {'⚠️ Alta exigencia' if tcpi and tcpi>1.1 else '✅ Alcanzable'}" if tcpi else f"{'TCPI':<35} {'N/D':>12}",
                "",
                f"DIAGNÓSTICO: {'⚠️ ATRASADO y SOBRE PRESUPUESTO' if spi and spi<1 and cpi and cpi<1 else '✅ En control' if spi and spi>=1 and cpi and cpi>=1 else '⚠️ Requiere atención'}",
            ]
            return "\n".join(lineas)

        # ── Estadística Descriptiva ────────────────────────────────────────────
        elif tipo == "estadisticas":
            vals = [float(x) for x in datos.get("valores", [])]
            if len(vals) < 2:
                return "Error: se necesitan al menos 2 valores en 'valores'."
            n = len(vals)
            s  = sorted(vals)
            mu = sum(vals) / n
            var = sum((x - mu) ** 2 for x in vals) / (n - 1)
            std = math.sqrt(var)
            med = (s[n//2-1] + s[n//2]) / 2 if n % 2 == 0 else s[n//2]
            q1  = s[n // 4]
            q3  = s[3 * n // 4]
            ric = q3 - q1
            cv  = std / mu * 100 if mu else 0
            sk  = sum(((x - mu) / std) ** 3 for x in vals) / n if std else 0
            ku  = sum(((x - mu) / std) ** 4 for x in vals) / n - 3 if std else 0
            outliers = [x for x in vals if x < q1 - 1.5*ric or x > q3 + 1.5*ric]
            return "\n".join([
                f"ESTADÍSTICA DESCRIPTIVA (n={n})",
                "=" * 45,
                f"Media              : {mu:>12.4f}",
                f"Mediana            : {med:>12.4f}",
                f"Desv. Estándar     : {std:>12.4f}",
                f"Varianza           : {var:>12.4f}",
                f"Mínimo             : {s[0]:>12.4f}",
                f"Máximo             : {s[-1]:>12.4f}",
                f"Rango              : {s[-1]-s[0]:>12.4f}",
                f"P25 (Q1)           : {q1:>12.4f}",
                f"P75 (Q3)           : {q3:>12.4f}",
                f"RIC (Q3-Q1)        : {ric:>12.4f}",
                f"Coef. Variación    : {cv:>11.2f}%",
                f"Asimetría (Skew)   : {sk:>12.4f}  {'→ asim. positiva' if sk>0.5 else '→ asim. negativa' if sk<-0.5 else '→ aproxim. simétrica'}",
                f"Curtosis (Excess)  : {ku:>12.4f}  {'→ leptocúrtica' if ku>0 else '→ platicúrtica'}",
                f"Outliers (IQR)     : {outliers if outliers else 'ninguno'}",
                f"Normalidad (aprox) : {'⚠️ posible asimetría' if abs(sk)>1 else '✅ distribución aproximadamente normal'}",
            ])

        # ── Regresión Lineal Simple ────────────────────────────────────────────
        elif tipo == "regresion":
            x = [float(v) for v in datos.get("x", [])]
            y = [float(v) for v in datos.get("y", [])]
            if len(x) != len(y) or len(x) < 2:
                return "Error: 'x' e 'y' deben tener el mismo tamaño (mínimo 2 puntos)."
            n   = len(x)
            sx  = sum(x); sy  = sum(y)
            sxx = sum(v**2 for v in x); sxy = sum(x[i]*y[i] for i in range(n))
            denom = n * sxx - sx**2
            if denom == 0:
                return "Error: todos los valores x son iguales, no se puede calcular regresión."
            b1  = (n * sxy - sx * sy) / denom
            b0  = (sy - b1 * sx) / n
            y_hat = [b0 + b1 * v for v in x]
            ss_res = sum((y[i] - y_hat[i])**2 for i in range(n))
            ss_tot = sum((v - sy/n)**2 for v in y)
            r2  = 1 - ss_res / ss_tot if ss_tot else 0
            r   = math.copysign(math.sqrt(abs(r2)), b1)
            return "\n".join([
                "REGRESIÓN LINEAL SIMPLE (y = b0 + b1·x)",
                "=" * 45,
                f"Intercepto b0      : {b0:>12.4f}",
                f"Pendiente b1       : {b1:>12.4f}",
                f"R² (coef. det.)    : {r2:>12.4f}  {'→ fuerte' if r2>=0.7 else '→ moderado' if r2>=0.4 else '→ débil'}",
                f"r  (Pearson)       : {r:>12.4f}",
                f"Ecuación           : y = {b0:.4f} + {b1:.4f}·x",
                f"n puntos           : {n}",
                f"SS residual        : {ss_res:>12.4f}",
                f"Interpretación     : {'correlación positiva fuerte' if r>0.7 else 'correlación negativa fuerte' if r<-0.7 else 'correlación moderada/débil'}",
            ])

        # ── CAGR ─────────────────────────────────────────────────────────────
        elif tipo == "cagr":
            vi  = float(datos.get("valor_inicial", 0))
            vf  = float(datos.get("valor_final",   0))
            per = float(datos.get("periodos", 1))
            if vi <= 0 or per <= 0:
                return "Error: valor_inicial y periodos deben ser positivos."
            cagr = (vf / vi) ** (1 / per) - 1
            return "\n".join([
                "CAGR — TASA DE CRECIMIENTO ANUAL COMPUESTO",
                "=" * 45,
                f"Valor inicial      : {vi:>12,.2f}",
                f"Valor final        : {vf:>12,.2f}",
                f"Períodos           : {per:>12.1f}",
                f"CAGR               : {cagr*100:>11.2f}%",
                f"Variación total    : {(vf/vi - 1)*100:>11.2f}%",
                f"Interpretación     : por cada período el valor {'crece' if cagr>0 else 'decrece'} un {abs(cagr)*100:.2f}%",
            ])

        # ── Punto de Equilibrio ────────────────────────────────────────────────
        elif tipo == "equilibrio":
            cf  = float(datos.get("costos_fijos", 0))
            pv_ = float(datos.get("precio_venta", 0))
            cv_ = float(datos.get("costo_variable", 0))
            if pv_ <= cv_:
                return "Error: el precio de venta debe ser mayor al costo variable unitario."
            mc      = pv_ - cv_
            pe_u    = cf / mc
            pe_monto = pe_u * pv_
            pe_pct  = cv_ / pv_ * 100
            return "\n".join([
                "ANÁLISIS PUNTO DE EQUILIBRIO",
                "=" * 45,
                f"Costos Fijos       : {cf:>12,.0f}",
                f"Precio Venta       : {pv_:>12,.0f}",
                f"Costo Variable     : {cv_:>12,.0f}",
                f"Margen Contribución: {mc:>12,.0f}  ({mc/pv_*100:.1f}%)",
                f"P.E. en Unidades   : {pe_u:>12,.1f} unidades",
                f"P.E. en Ventas     : ${pe_monto:>11,.0f}",
                f"Ratio CV/PV        : {pe_pct:>11.1f}%",
                f"Interpretación     : sobre {pe_u:.0f} unidades el proyecto genera utilidad.",
            ])

        return f"Tipo '{tipo}' no reconocido. Opciones: van_tir, evm, estadisticas, equilibrio, regresion, cagr"
    except (KeyError, ValueError, TypeError) as e:
        return f"Error en datos para calcular_financiero ({tipo}): {e}"
    except Exception as e:
        logger.exception("calcular_financiero %s", tipo)
        return f"Error inesperado en calcular_financiero: {e}"
