# -*- coding: utf-8 -*-
"""
core/tools/chile.py — Herramientas de datos externos (indicadores/energia/
macro/CMF de Chile + resultados deportivos).

Extraido de core/tools.py (2026-07-26, Strangler Fig v1.3, incremento 3/N):
consultas HTTP a fuentes de datos publicas via core.web_monitor._get (import
local por funcion). El dispatcher (core/tools.py) importa estas 5 tools.
"""
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def _consultar_indicadores_chile() -> str:
    """Consulta indicadores económicos de Chile del Banco Central."""
    try:
        from core.web_monitor import _get
        # Intentar API del Banco Central de Chile
        url    = "https://mindicador.cl/api"
        data   = await _get(url)
        if not isinstance(data, dict):
            raise ValueError("Respuesta inesperada")
        uf     = data.get("uf",    {}).get("valor", "N/D")
        dolar  = data.get("dolar", {}).get("valor", "N/D")
        euro   = data.get("euro",  {}).get("valor", "N/D")
        ipc    = data.get("ipc",   {}).get("valor", "N/D")
        fecha  = datetime.now().strftime("%d/%m/%Y")
        return (
            f"Indicadores económicos Chile al {fecha}:\n"
            f"• UF: ${uf:,.2f} CLP\n"
            f"• Dólar USA: ${dolar:,.2f} CLP\n"
            f"• Euro: ${euro:,.2f} CLP\n"
            f"• IPC: {ipc}%\n"
            f"Fuente: Banco Central de Chile (mindicador.cl)"
        )
    except Exception as e:
        logger.warning("_consultar_indicadores_chile: %s", e)
        return (
            "No se pudo conectar al Banco Central. "
            "Valores de referencia aproximados (pueden no ser actuales):\n"
            "• UF: ~$38,000 CLP\n• Dólar: ~$950 CLP\n• Euro: ~$1,030 CLP"
        )


async def _obtener_energia_chile(tipo: str = "solar_eolico") -> str:
    """Obtiene datos del mercado eléctrico chileno."""
    try:
        from core.web_monitor import fetch_categoria
        cat_map = {
            "solar_eolico": "energia_renovable",
            "demanda":      "energia_demanda",
            "spot":         "energia_spot",
        }
        categoria = cat_map.get(tipo, "energia_renovable")
        data = await fetch_categoria(categoria)
        if "error" in data:
            return f"Error al obtener datos de energía: {data['error']}"

        if categoria == "energia_renovable":
            solar  = data.get("solar",  {})
            eolico = data.get("eolico", {})
            return (
                f"Energía Renovable Chile (Santiago):\n"
                f"• Solar: {solar.get('promedio_wm2','?')} W/m² prom, "
                f"{solar.get('maximo_wm2','?')} W/m² máx — Potencial: {solar.get('potencial','?')}\n"
                f"• Eólico: {eolico.get('velocidad_prom_kmh','?')} km/h — Potencial: {eolico.get('potencial','?')}\n"
                f"• {data.get('recomendacion_renovable','')}\n"
                f"Período: {data.get('periodo','?')}"
            )
        elif categoria == "energia_demanda":
            temp = data.get("temperatura", {})
            dem  = data.get("demanda_estimada", {})
            return (
                f"Demanda Eléctrica Estimada Chile:\n"
                f"• Hoy: {temp.get('hoy_prom_c','?')}°C → Demanda {dem.get('hoy','?')}\n"
                f"• Mañana: {temp.get('manana_prom_c','?')}°C → Demanda {dem.get('manana','?')}\n"
                f"• Alerta: {data.get('alerta','Sin alertas')}"
            )
        else:
            return json.dumps(data, ensure_ascii=False, indent=2)[:1000]
    except Exception as e:
        return f"Error al obtener datos de energía: {e}"


async def _obtener_partidos(consulta: str) -> str:
    """Obtiene resultados y estadísticas de fútbol."""
    try:
        from core.web_monitor import fetch_futbol_equipo
        data = await fetch_futbol_equipo(consulta)
        if "error" in data:
            return f"No se encontró '{consulta}' en TheSportsDB. Prueba con el nombre en inglés."

        st = data.get("estadisticas", {})
        ultimos = data.get("ultimos_partidos", [])[:5]
        proximos = data.get("proximos_partidos", [])[:3]

        resultado = (
            f"📊 {data.get('nombre')} ({data.get('pais')} · {data.get('liga')})\n\n"
            f"Estadísticas recientes:\n"
            f"• Partidos: {st.get('partidos',0)}\n"
            f"• Victorias: {st.get('victorias',0)} ({st.get('pct_victoria',0)}%)\n"
            f"• Empates: {st.get('empates',0)} ({st.get('pct_empate',0)}%)\n"
            f"• Derrotas: {st.get('derrotas',0)} ({st.get('pct_derrota',0)}%)\n"
            f"• Goles favor/contra: {st.get('goles_favor',0)}/{st.get('goles_contra',0)}\n"
            f"• Tendencia: {st.get('tendencia','?')} | Racha: {st.get('racha_ultimos_5','?')}\n"
        )
        if ultimos:
            resultado += f"\nÚltimos partidos:\n" + "\n".join(f"  {p}" for p in ultimos)
        if proximos:
            resultado += f"\nPróximos partidos:\n" + "\n".join(f"  {p}" for p in proximos)
        return resultado
    except Exception as e:
        return f"Error al obtener datos de fútbol: {e}"


async def _consultar_macro_chile(indicadores: list[str] | None = None, historico: bool = False) -> str:
    """Consulta indicadores macroeconómicos de Chile desde mindicador.cl."""
    NOMBRES = {
        "uf":           ("UF",              "CLP",  True),
        "utm":          ("UTM",             "CLP",  True),
        "tpm":          ("TPM (Banco Central)", "%", False),
        "ipc":          ("IPC (inflación)",    "%",  False),
        "imacec":       ("IMACEC",             "%",  False),
        "tasa_desempleo": ("Desempleo",         "%",  False),
        "dolar":        ("Dólar USD",          "CLP", True),
        "euro":         ("Euro",               "CLP", True),
        "libra_cobre":  ("Libra de Cobre",     "USD", True),
    }
    todos = list(NOMBRES.keys())
    claves = [i for i in (indicadores or todos) if i in NOMBRES]
    if not claves:
        claves = todos

    try:
        from core.web_monitor import _get
        data = await _get("https://mindicador.cl/api")
        if not isinstance(data, dict):
            raise ValueError("Respuesta inesperada de mindicador.cl")

        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        lineas = [
            f"INDICADORES MACROECONÓMICOS CHILE — {fecha}",
            f"Fuente: Banco Central de Chile (mindicador.cl)",
            "=" * 55,
        ]
        for clave in claves:
            nombre, unidad, es_moneda = NOMBRES[clave]
            entry = data.get(clave, {})
            val   = entry.get("valor", "N/D")
            fecha_val = entry.get("fecha", "")[:10] if isinstance(entry.get("fecha"), str) else ""
            if isinstance(val, (int, float)):
                val_fmt = f"${val:,.2f}" if es_moneda else f"{val:.2f}"
            else:
                val_fmt = str(val)
            lineas.append(f"  {nombre:<28}: {val_fmt:>10} {unidad}  ({fecha_val})")

        # Serie histórica del primero si se pide
        if historico and claves:
            c = claves[0]
            nombre_c = NOMBRES[c][0]
            try:
                hist = await _get(f"https://mindicador.cl/api/{c}")
                serie = hist.get("serie", [])[:12]
                lineas += ["", f"Historial {nombre_c} (últimos {len(serie)} registros):"]
                for item in serie:
                    d = item.get("fecha", "")[:10]
                    v = item.get("valor", "?")
                    lineas.append(f"  {d}: {v}")
            except Exception:
                lineas.append(f"  (historial no disponible)")
        return "\n".join(lineas)

    except Exception as e:
        logger.warning("_consultar_macro_chile: %s", e)
        return (
            "No se pudo conectar al Banco Central (mindicador.cl).\n"
            "Valores de referencia aproximados (julio 2026):\n"
            "  UF: ~$39.500 CLP | Dólar: ~$960 CLP | TPM: ~5.5% | IPC: ~4.2%"
        )


async def _buscar_empresa_cmf(nombre_empresa: str = "", rut: str = "") -> str:
    """Busca empresas en el registro público de la CMF Chile."""
    # Mapa de empresas conocidas → RUT (sin puntos ni guión)
    EMPRESAS_CONOCIDAS = {
        "falabella": "76645030", "soquimich": "93007000", "sqm": "93007000",
        "bci": "97006000", "banco bci": "97006000",
        "santander": "97036000", "banco santander": "97036000",
        "entel": "92580000", "enersis": "90813000",
        "codelco": "61704000", "endesa": "91081000",
        "cencosud": "93834000", "lan": "89862200", "latam": "89862200",
        "ripley": "76542310", "paris": "96874030",
        "bsantander": "97036000", "itau": "76645030",
    }

    try:
        from core.web_monitor import _get

        # Determinar RUT
        rut_buscar = rut
        if not rut_buscar and nombre_empresa:
            clave = nombre_empresa.lower().strip()
            for k, v in EMPRESAS_CONOCIDAS.items():
                if k in clave or clave in k:
                    rut_buscar = v
                    break

        if not rut_buscar and not nombre_empresa:
            return "Error: proporciona 'nombre_empresa' o 'rut' para buscar en CMF."

        # Búsqueda por nombre en el API público de CMF
        if not rut_buscar:
            url = f"https://api.cmfchile.cl/api-sbifv3/recursos/empresa?nombre={nombre_empresa}&formato=json"
            try:
                resp = await _get(url)
                empresas = resp.get("Empresas", resp.get("Empresa", []))
                if isinstance(empresas, dict):
                    empresas = [empresas]
                if not empresas:
                    return (
                        f"No se encontró '{nombre_empresa}' en el registro CMF.\n"
                        f"Prueba con el nombre exacto o proporciona el RUT de la empresa.\n"
                        f"Empresas con datos disponibles: Falabella, SQM, BCI, Entel, Santander, Cencosud, Endesa, LATAM."
                    )
                # Usar el primer resultado
                emp = empresas[0]
                rut_buscar = emp.get("RUTEntidad", "").replace(".", "").replace("-", "")
                lineas = [
                    f"EMPRESA ENCONTRADA EN CMF:",
                    f"  Nombre: {emp.get('RazonSocial', nombre_empresa)}",
                    f"  RUT: {emp.get('RUTEntidad', 'N/D')}",
                    f"  Tipo: {emp.get('TipoEmisor', 'N/D')}",
                ]
            except Exception:
                return (
                    f"No se pudo consultar la API CMF para '{nombre_empresa}'.\n"
                    f"La API CMF requiere acceso autorizado. Proporciona el RUT directamente o usa datos públicos."
                )

        # Si tenemos RUT, obtener información básica
        lineas = [
            f"INFORMACIÓN CMF — {nombre_empresa.upper() or rut_buscar}",
            "=" * 55,
            f"RUT consultado     : {rut_buscar}",
            "",
            "Para estados financieros completos consulta:",
            f"  https://www.cmfchile.cl/portal/estadisticas/617/w3-propertyvalue-29404.html",
            f"  https://api.cmfchile.cl/api-sbifv3/recursos/empresa/{rut_buscar}/balances?formato=json",
            "",
            "Nota: El acceso a balances detallados requiere API key de CMF.",
            "Regístrate gratis en: https://api.cmfchile.cl/",
            "",
            "Fuentes alternativas con datos financieros públicos:",
            "  • Memoriachilena.cl — estados financieros históricos",
            "  • SVS/CMF portal    — EEFF trimestrales",
            "  • Bolsa de Santiago — precios y ratios de mercado",
        ]
        return "\n".join(lineas)

    except Exception as e:
        logger.warning("_buscar_empresa_cmf: %s", e)
        return f"Error al consultar CMF: {e}"
