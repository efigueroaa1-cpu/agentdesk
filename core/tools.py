"""
core/tools.py — Herramientas disponibles para los agentes (Tool Calling).

Cada herramienta tiene:
  - Definición JSON (schema que entiende Groq/OpenAI)
  - Implementación Python (lo que realmente ejecuta)

Herramientas:
  buscar_web             → búsqueda en internet con IA (Tavily)
  obtener_pagina         → lee el contenido de cualquier URL o documento
  leer_archivo           → lee CSVs/Excel/texto subidos por el usuario
  calcular               → matemáticas precisas sin errores de redondeo
  calcular_financiero    → VAN/TIR/TIRM/Payback/EVM/estadísticas/regresión
  consultar_indicadores  → UF, dólar, IPC del Banco Central Chile
  consultar_macro_chile  → macro completa: TPM, IMACEC, desempleo, PIB, UF, dólar
  buscar_empresa_cmf     → datos financieros de empresas en CMF Chile
  obtener_energia_chile  → datos del mercado eléctrico chileno
  obtener_partidos       → resultados de fútbol de equipos/ligas
  listar_archivos        → muestra archivos disponibles del usuario
  consultar_a_otro_agente → delega una subtarea a OTRO agente (ADR-0011)
"""
from __future__ import annotations
import ast
import json
import logging
import math
import operator
from datetime import datetime

from core.key_vault import obtener_key

logger = logging.getLogger(__name__)

# Secreto via el accesor sancionado (vault cifrado -> .env), NUNCA os.environ
# directo (ADR-0011 [TOOL-SECURITY]: una herramienta no lee el entorno del
# host) ni hardcodeado. "" si no esta configurada -> degradacion limpia.
_TAVILY_KEY = obtener_key("AGENTDESK_TAVILY_KEY") or ""

# Referencia al orquestador vivo, inyectada al arrancar la API/CLI (mismo
# patrón que core/scheduler.py: un global de módulo, sin importar la capa
# api). La usa consultar_a_otro_agente (ADR-0011) para ubicar al agente
# destino de una delegación.
_orquestador_ref = None


def set_orquestador(orquestador) -> None:
    """Inyecta la referencia al orquestador vivo. Llamar al arrancar la API/CLI."""
    global _orquestador_ref
    _orquestador_ref = orquestador

# ── Definiciones de herramientas (schema OpenAI-compatible) ───────────────────
from core.tools_schema import TOOLS_SCHEMA  # schema extraido (Strangler Fig v1.3)


# ── Implementaciones ──────────────────────────────────────────────────────────

async def _listar_archivos() -> str:
    """Lista todos los archivos subidos por el usuario."""
    try:
        from core.path_manager import data_path
        uploads_dir = data_path("uploads")
        if not uploads_dir.exists():
            return "No hay archivos subidos todavía."
        archivos = []
        for f in sorted(uploads_dir.glob("*.meta.json"),
                        key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
                kb   = round(meta.get("tamano_bytes", 0) / 1024, 1)
                archivos.append(
                    f"- {meta['nombre_original']} "
                    f"(ID: {meta['archivo_id']}, {kb} KB, tipo: {meta['tipo']})"
                )
            except Exception:
                pass
        return "Archivos disponibles:\n" + "\n".join(archivos) if archivos else "No hay archivos subidos."
    except Exception as e:
        return f"Error al listar archivos: {e}"


async def _leer_archivo(archivo_id: str | None = None, max_chars: int = 8000) -> str:
    """Lee el contenido de un archivo subido con preview estructurado para CSV/Excel."""
    try:
        from core.path_manager import data_path
        uploads_dir = data_path("uploads")

        if archivo_id:
            meta_path = uploads_dir / f"{archivo_id}.meta.json"
        else:
            metas = sorted(uploads_dir.glob("*.meta.json"),
                           key=lambda x: x.stat().st_mtime, reverse=True)
            if not metas:
                return "No hay archivos subidos. Pide al usuario que suba un archivo primero."
            meta_path = metas[0]

        if not meta_path.exists():
            return f"Archivo {archivo_id} no encontrado. Usa listar_archivos para ver los disponibles."

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        ruta = uploads_dir / meta["nombre_interno"]
        if not ruta.exists():
            return "El archivo existe en el registro pero no en disco."

        nombre = meta["nombre_original"]
        ext    = meta.get("tipo", "").lower()
        kb     = round(meta.get("tamano_bytes", 0) / 1024, 1)

        # ── CSV ──────────────────────────────────────────────────────────────
        if ext == "csv":
            import io, csv as _csv
            texto    = ruta.read_bytes().decode("utf-8", errors="replace")
            try:
                dialecto = _csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|")
                sep      = dialecto.delimiter
            except Exception:
                sep = ","
            reader  = _csv.DictReader(io.StringIO(texto), delimiter=sep)
            columnas = reader.fieldnames or []
            filas    = list(reader)
            n_filas  = len(filas)

            # Estadísticas por columna
            stats_lineas = []
            for col in columnas[:20]:
                vals = [f[col] for f in filas if f.get(col, "").strip()]
                nums = []
                for v in vals:
                    try: nums.append(float(v.replace(",", "").replace("$", "").replace("%", "")))
                    except Exception: pass
                if nums:
                    stats_lineas.append(
                        f"  {col}: numérico — mín={min(nums):,.2f}, máx={max(nums):,.2f}, "
                        f"prom={sum(nums)/len(nums):,.2f} ({len(nums)} valores)"
                    )
                else:
                    muestra_vals = list(dict.fromkeys(v for v in vals if v))[:5]
                    stats_lineas.append(f"  {col}: texto — ej: {', '.join(muestra_vals)}")

            # Primeras filas como tabla
            header_line = " | ".join(str(c) for c in columnas[:10])
            filas_txt   = []
            for fila in filas[:10]:
                filas_txt.append(" | ".join(str(fila.get(c,"")) for c in columnas[:10]))

            resumen = (
                f"Archivo: {nombre} ({kb} KB, {n_filas} filas, {len(columnas)} columnas)\n"
                f"Columnas: {', '.join(columnas)}\n\n"
                f"Estadísticas:\n" + "\n".join(stats_lineas) + "\n\n"
                f"Primeras filas:\n{header_line}\n" + "\n".join(filas_txt)
            )
            return resumen[:max_chars]

        # ── Excel ─────────────────────────────────────────────────────────────
        elif ext in ("xlsx", "xls"):
            try:
                import openpyxl
                wb    = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
                sheet = wb.active
                filas_raw = list(sheet.iter_rows(values_only=True))
                wb.close()
                if not filas_raw:
                    return f"Archivo Excel vacío: {nombre}"
                encabezado = [str(c) if c is not None else "" for c in filas_raw[0]]
                datos      = [
                    {encabezado[i]: (str(v) if v is not None else "")
                     for i, v in enumerate(fila) if i < len(encabezado)}
                    for fila in filas_raw[1:]
                ]
                n_filas = len(datos)
                # Estadísticas básicas
                stats_lineas = []
                for col in encabezado[:15]:
                    vals = [d[col] for d in datos if d.get(col, "").strip()]
                    nums = []
                    for v in vals:
                        try: nums.append(float(v.replace(",", "").replace("$", "").replace("%", "")))
                        except Exception: pass
                    if nums:
                        stats_lineas.append(
                            f"  {col}: numérico — mín={min(nums):,.2f}, máx={max(nums):,.2f}, "
                            f"prom={sum(nums)/len(nums):,.2f}"
                        )
                    else:
                        muestra_vals = list(dict.fromkeys(v for v in vals if v))[:4]
                        stats_lineas.append(f"  {col}: texto — ej: {', '.join(muestra_vals)}")

                header_line = " | ".join(encabezado[:10])
                filas_txt   = [
                    " | ".join(str(d.get(c,"")) for c in encabezado[:10])
                    for d in datos[:10]
                ]
                resumen = (
                    f"Archivo: {nombre} ({kb} KB, {n_filas} filas, {len(encabezado)} columnas)\n"
                    f"Columnas: {', '.join(encabezado)}\n\n"
                    f"Estadísticas:\n" + "\n".join(stats_lineas) + "\n\n"
                    f"Primeras filas:\n{header_line}\n" + "\n".join(filas_txt)
                )
                return resumen[:max_chars]
            except ImportError:
                pass  # fallback to raw read below

        # ── Texto plano / fallback ────────────────────────────────────────────
        contenido = ruta.read_bytes().decode("utf-8", errors="replace")
        if len(contenido) > max_chars:
            contenido = contenido[:max_chars] + f"\n... [truncado — {kb} KB total]"
        return f"Archivo: {nombre}\nContenido:\n{contenido}"

    except Exception as e:
        return f"Error al leer archivo: {e}"


# Evaluador matemático por AST con lista blanca: a diferencia de eval() con
# builtins vacíos (escapable vía atributos), aquí cualquier nodo no listado
# (atributos, subíndices, lambdas, imports) se rechaza de plano.
_CALC_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sum": sum, "len": len, "pow": pow,
    "sqrt": math.sqrt, "log": math.log,
    "floor": math.floor, "ceil": math.ceil,
}
_CALC_CONSTS = {"pi": math.pi, "e": math.e}
_CALC_BINOPS = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}


def _eval_matematica(nodo):
    """Evalúa recursivamente solo nodos aritméticos permitidos."""
    if isinstance(nodo, ast.Expression):
        return _eval_matematica(nodo.body)
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _CALC_BINOPS:
        return _CALC_BINOPS[type(nodo.op)](_eval_matematica(nodo.left), _eval_matematica(nodo.right))
    if isinstance(nodo, ast.UnaryOp) and isinstance(nodo.op, (ast.UAdd, ast.USub)):
        v = _eval_matematica(nodo.operand)
        return v if isinstance(nodo.op, ast.UAdd) else -v
    if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            and nodo.func.id in _CALC_FUNCS and not nodo.keywords):
        return _CALC_FUNCS[nodo.func.id](*[_eval_matematica(a) for a in nodo.args])
    if isinstance(nodo, ast.Name) and nodo.id in _CALC_CONSTS:
        return _CALC_CONSTS[nodo.id]
    if isinstance(nodo, (ast.List, ast.Tuple)):
        return [_eval_matematica(e) for e in nodo.elts]
    raise ValueError(f"operación no permitida: {type(nodo).__name__}")


async def _calcular(expresion: str, descripcion: str = "") -> str:
    """Evalúa una expresión matemática de forma segura (AST, sin eval)."""
    try:
        arbol     = ast.parse(expresion, mode="eval")
        resultado = _eval_matematica(arbol)
        resultado_fmt = f"{resultado:,.2f}" if isinstance(resultado, float) else f"{resultado:,}"
        ctx = f" ({descripcion})" if descripcion else ""
        return f"Resultado{ctx}: {resultado_fmt}\n(expresión: {expresion} = {resultado})"
    except ZeroDivisionError:
        return "Error: división por cero."
    except Exception as e:
        return f"Error en cálculo '{expresion}': {e}"


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


# ── Implementaciones nuevas ────────────────────────────────────────────────────

from core.tools_finance import _calcular_financiero  # finanzas extraidas (Strangler Fig v1.3)

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


async def _buscar_web(query: str, max_resultados: int = 6) -> str:
    """Busca en internet usando Tavily AI Search."""
    import httpx
    if not _TAVILY_KEY:
        return ("Busqueda web no disponible: falta AGENTDESK_TAVILY_KEY en el "
                ".env (la herramienta degrada limpio, no rompe la tarea).")
    try:
        max_resultados = min(max(1, int(max_resultados)), 10)
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": _TAVILY_KEY,
                    "query": query,
                    "max_results": max_resultados,
                    "search_depth": "advanced",
                    "include_answer": True,
                    "include_raw_content": False,
                    "include_domains": [],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        lineas = [f"BÚSQUEDA WEB: {query}", "=" * 65]

        if data.get("answer"):
            lineas += ["RESUMEN IA:", data["answer"], ""]

        resultados = data.get("results", [])
        lineas.append(f"RESULTADOS ({len(resultados)} encontrados):")
        for i, r in enumerate(resultados, 1):
            titulo  = r.get("title", "Sin título")
            url     = r.get("url", "")
            snippet = (r.get("content") or "")[:400]
            score   = r.get("score", 0)
            lineas += [
                f"\n[{i}] {titulo}",
                f"    URL: {url}",
                f"    Relevancia: {score:.2f}",
                f"    {snippet}{'...' if len(r.get('content',''))>400 else ''}",
            ]

        return "\n".join(lineas)

    except httpx.HTTPStatusError as e:
        return f"Error Tavily ({e.response.status_code}): {e.response.text[:200]}"
    except Exception as e:
        logger.warning("_buscar_web: %s", e)
        return f"Error en búsqueda web: {e}"


async def _obtener_pagina(url: str, max_chars: int = 8000) -> str:
    """Obtiene el contenido de una URL usando Tavily Extract, con fallback HTTP."""
    import httpx, re
    max_chars = min(int(max_chars), 20000)

    # ── Intento 1: Tavily Extract (maneja HTML y algunos PDFs) ───────────────
    # Sin clave, se salta directo al fallback HTTP (degradacion limpia).
    try:
        if not _TAVILY_KEY:
            raise RuntimeError("AGENTDESK_TAVILY_KEY no configurada")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.tavily.com/extract",
                json={"api_key": _TAVILY_KEY, "urls": [url]},
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results", [])
        if results:
            content = (results[0].get("raw_content") or "").strip()
            if content and len(content) > 100:
                header = f"CONTENIDO DE: {url}\n{'=' * 65}\n"
                if len(content) > max_chars:
                    content = content[:max_chars] + f"\n\n[... truncado — {len(content):,} caracteres en total]"
                return header + content
    except Exception as e:
        logger.debug("_obtener_pagina Tavily Extract falló: %s — intentando HTTP directo", e)

    # ── Intento 2: HTTP directo + limpieza HTML ───────────────────────────────
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "").lower()

            if "pdf" in ct or url.lower().endswith(".pdf"):
                return (
                    f"[Documento PDF detectado: {url}]\n"
                    f"Tavily no pudo extraer su contenido. Intenta buscar la versión HTML "
                    f"o el resumen ejecutivo del documento."
                )

            html = resp.text
            # Eliminar scripts, estilos y tags
            texto = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            texto = re.sub(r"<[^>]+>", " ", texto)
            texto = re.sub(r"&[a-z]+;", " ", texto)
            texto = re.sub(r"\s{2,}", "\n", texto).strip()

            if len(texto) > max_chars:
                texto = texto[:max_chars] + f"\n\n[... truncado — {len(texto):,} caracteres en total]"

            return f"CONTENIDO DE: {url}\n{'=' * 65}\n{texto}"

    except Exception as e:
        return f"No se pudo obtener '{url}': {e}"


# ── Dispatcher: nombre → función ──────────────────────────────────────────────

async def _consultar_a_otro_agente(agente_id: str, pregunta: str, *,
                                    origen_id: str = "", user_id: str = "anonimo") -> str:
    """Delegación cognitiva (ADR-0011): pide ayuda a otro agente y retorna su respuesta."""
    if _orquestador_ref is None:
        return "Delegación no disponible: orquestador no inicializado."
    from core.services.delegation_service import DelegationService
    servicio = DelegationService(lambda: _orquestador_ref)
    return await servicio.speak(origen_id or "desconocido", agente_id, pregunta,
                                 user_id=user_id)


def _proponer_comando_ot(*, adaptador: str, tag_id: str, valor,
                          justificacion: str, agente_id: str,
                          user_id: str) -> str:
    """
    Propuesta de escritura OT (ADR-0024). El agente jamas ejecuta: crea
    una propuesta que pasa el filtro determinista de limites fisicos y
    queda PENDIENTE de la aprobacion de un operador supervisor+.
    """
    from core.services.ot_command_service import ot_service
    resultado = ot_service.proponer(
        adaptador=adaptador, tag_id=tag_id, valor=valor,
        justificacion=justificacion, agente_id=agente_id, user_id=user_id,
    )
    if not resultado["ok"]:
        return f"PROPUESTA RECHAZADA: {resultado['detalle']}"
    return (f"Propuesta #{resultado['propuesta_id']} creada: "
            f"{adaptador}.{tag_id} = {valor}. {resultado['detalle']}. "
            "Informa al operador que debe aprobarla en el panel Monitor > Acciones OT.")


async def ejecutar_herramienta(nombre: str, argumentos: dict, *,
                                agente_id_clave: str = "", user_id: str = "anonimo") -> str:
    """Ejecuta una herramienta por nombre y devuelve el resultado como string."""
    logger.info("Tool call: %s(%s)", nombre, list(argumentos.keys()))
    from core.telemetry_otel import medir_paso
    with medir_paso("tool.ejecutar", herramienta=nombre, agente=agente_id_clave):
        return await _despachar_herramienta(nombre, argumentos,
                                            agente_id_clave=agente_id_clave, user_id=user_id)


async def _despachar_herramienta(nombre: str, argumentos: dict, *,
                                  agente_id_clave: str = "", user_id: str = "anonimo") -> str:
    try:
        if nombre == "consultar_a_otro_agente":
            return await _consultar_a_otro_agente(
                argumentos["agente_id"], argumentos["pregunta"],
                origen_id=agente_id_clave, user_id=user_id,
            )
        if nombre == "proponer_comando_ot":
            return _proponer_comando_ot(
                adaptador     = argumentos["adaptador"],
                tag_id        = argumentos["tag_id"],
                valor         = argumentos["valor"],
                justificacion = argumentos["justificacion"],
                agente_id     = agente_id_clave,
                user_id       = user_id,
            )
        if nombre == "buscar_web":
            return await _buscar_web(
                query          = argumentos["query"],
                max_resultados = argumentos.get("max_resultados", 6),
            )
        if nombre == "obtener_pagina":
            return await _obtener_pagina(
                url       = argumentos["url"],
                max_chars = argumentos.get("max_chars", 8000),
            )
        if nombre == "listar_archivos":
            return await _listar_archivos()
        if nombre == "leer_archivo":
            return await _leer_archivo(
                archivo_id = argumentos.get("archivo_id"),
                max_chars  = argumentos.get("max_chars", 8000),
            )
        if nombre == "calcular":
            return await _calcular(
                expresion  = argumentos["expresion"],
                descripcion= argumentos.get("descripcion", ""),
            )
        if nombre == "calcular_financiero":
            return await _calcular_financiero(
                tipo  = argumentos["tipo"],
                datos = argumentos.get("datos", {}),
            )
        if nombre == "consultar_macro_chile":
            return await _consultar_macro_chile(
                indicadores = argumentos.get("indicadores"),
                historico   = argumentos.get("historico", False),
            )
        if nombre == "buscar_empresa_cmf":
            return await _buscar_empresa_cmf(
                nombre_empresa = argumentos.get("nombre_empresa", ""),
                rut            = argumentos.get("rut", ""),
            )
        if nombre == "consultar_indicadores_chile":
            return await _consultar_indicadores_chile()
        if nombre == "obtener_energia_chile":
            return await _obtener_energia_chile(argumentos.get("tipo", "solar_eolico"))
        if nombre == "obtener_partidos":
            return await _obtener_partidos(argumentos["consulta"])
        return f"Herramienta '{nombre}' no reconocida."
    except Exception as e:
        logger.error("ejecutar_herramienta '%s': %s", nombre, e)
        return f"Error ejecutando {nombre}: {e}"
