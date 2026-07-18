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

logger = logging.getLogger(__name__)

_TAVILY_KEY = "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"

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

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "buscar_web",
            "description": (
                "Busca información actualizada en internet. "
                "Úsala para encontrar: memorias anuales de empresas chilenas, informes del Banco Central (IPoM), "
                "noticias financieras recientes, estados financieros, documentos de la CMF, precios de mercado. "
                "Devuelve un resumen y los resultados más relevantes con sus URLs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Consulta de búsqueda. Sé específico para mejores resultados. "
                            "Ej: 'memoria anual 2024 Cristales Chile CMF', "
                            "'Informe Política Monetaria junio 2025 Banco Central Chile PDF', "
                            "'estados financieros SQM 2023'"
                        ),
                    },
                    "max_resultados": {
                        "type": "integer",
                        "description": "Número de resultados (1-10). Default 6.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_pagina",
            "description": (
                "Obtiene el contenido completo de una página web o documento. "
                "Úsala con URLs encontradas en buscar_web para leer el contenido de: "
                "memorias anuales, informes PDF del Banco Central, páginas de CMF, reportes de empresas. "
                "Puede procesar páginas HTML y documentos en línea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL de la página o documento a leer.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Máximo de caracteres a retornar. Default 8000.",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_archivos",
            "description": "Lista todos los archivos CSV, Excel y texto que el usuario ha subido. Úsala primero para saber qué archivos hay disponibles.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_archivo",
            "description": "Lee el contenido de un archivo subido por el usuario (CSV, Excel, JSON, TXT). Si no sabes el archivo_id, usa listar_archivos primero.",
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo_id": {
                        "type": "string",
                        "description": "ID del archivo (ej: 'f6a22548'). Opcional — si no se da, lee el más reciente.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Máximo de caracteres a leer. Default 8000.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular",
            "description": "Realiza cálculos matemáticos PRECISOS. Úsala siempre para sumas, restas, porcentajes, diferencias de presupuesto, etc. Evita calcular mentalmente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expresion": {
                        "type": "string",
                        "description": "Expresión matemática Python válida. Ej: '213050821 - 135014725' o '(50000 - 43478) / 43478 * 100'",
                    },
                    "descripcion": {
                        "type": "string",
                        "description": "Qué se está calculando, para contexto. Ej: 'Diferencia entre presupuesto y gasto real'",
                    },
                },
                "required": ["expresion"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_indicadores_chile",
            "description": "Obtiene indicadores económicos actuales de Chile: valor de la UF, dólar americano, euro y otros del Banco Central.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_energia_chile",
            "description": "Obtiene datos del mercado eléctrico chileno: radiación solar, velocidad del viento, estimación de demanda eléctrica y tendencias de energía renovable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {
                        "type": "string",
                        "enum": ["solar_eolico", "demanda", "spot"],
                        "description": "Tipo de datos: solar_eolico (generación renovable), demanda (consumo estimado), spot (precio del mercado)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_financiero",
            "description": (
                "Realiza cálculos financieros y estadísticos especializados sin errores de redondeo. "
                "Úsala SIEMPRE para: VAN/TIR/Payback de proyectos, métricas EVM de control de proyectos "
                "(SPI/CPI/EAC/VAC/TCPI), estadísticas descriptivas, regresión lineal, CAGR, punto de equilibrio."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {
                        "type": "string",
                        "enum": ["van_tir", "evm", "estadisticas", "equilibrio", "regresion", "cagr"],
                        "description": (
                            "van_tir: VAN, TIR, TIRM, Payback (datos: flujos[], tasa, tasa_reinversion?). "
                            "evm: SPI/CPI/EAC/VAC/TCPI (datos: bac, pv, ev, ac). "
                            "estadisticas: descriptiva completa (datos: valores[]). "
                            "equilibrio: punto de equilibrio (datos: costos_fijos, precio_venta, costo_variable). "
                            "regresion: regresión lineal simple (datos: x[], y[]). "
                            "cagr: tasa de crecimiento compuesto (datos: valor_inicial, valor_final, periodos)."
                        ),
                    },
                    "datos": {
                        "type": "object",
                        "description": "Parámetros según el tipo. Ver descripción del campo 'tipo'.",
                    },
                },
                "required": ["tipo", "datos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_macro_chile",
            "description": (
                "Obtiene indicadores macroeconómicos actuales e históricos de Chile en tiempo real. "
                "Cubre: UF, TPM (Tasa Política Monetaria), IPC (inflación), IMACEC, tasa de desempleo, "
                "dólar USD, euro, libra de cobre. Fuente: Banco Central de Chile vía mindicador.cl."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "indicadores": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Lista de indicadores a consultar. Opciones: 'uf', 'tpm', 'ipc', 'imacec', "
                            "'desempleo', 'dolar', 'euro', 'libra_cobre', 'utm'. "
                            "Si se omite, retorna todos los principales."
                        ),
                    },
                    "historico": {
                        "type": "boolean",
                        "description": "Si True, incluye los últimos 12 meses de datos históricos del primer indicador.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_empresa_cmf",
            "description": (
                "Busca información financiera de empresas chilenas en la CMF (Comisión para el Mercado Financiero). "
                "Retorna datos de la empresa, emisores registrados y links a estados financieros. "
                "Úsala para analizar empresas públicas chilenas: Falabella, BCI, SQM, Codelco, Entel, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_empresa": {
                        "type": "string",
                        "description": "Nombre de la empresa chilena a buscar. Ej: 'Falabella', 'SQM', 'BCI'.",
                    },
                    "rut": {
                        "type": "string",
                        "description": "RUT de la empresa sin puntos ni guión (opcional si se da nombre).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_partidos",
            "description": "Obtiene resultados, estadísticas y tendencias de fútbol. Funciona con equipos (Real Madrid, Colo-Colo, Chile) o ligas (Premier League, La Liga).",
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "Nombre del equipo o liga. Ej: 'Real Madrid', 'Premier League', 'Chile'",
                    },
                },
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_a_otro_agente",
            "description": (
                "Delega una subtarea a OTRO agente del sistema y espera su respuesta. "
                "Úsalo cuando la consulta necesita el conocimiento o el rol de un agente "
                "distinto al tuyo (ej. un agente de Finanzas necesita un dato de "
                "Mantenimiento). No lo uses para delegarte una tarea a ti mismo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agente_id": {
                        "type": "string",
                        "description": "ID del agente al que se delega la subtarea.",
                    },
                    "pregunta": {
                        "type": "string",
                        "description": "La subtarea o pregunta concreta a delegar.",
                    },
                },
                "required": ["agente_id", "pregunta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "proponer_comando_ot",
            "description": (
                "PROPONE un comando de escritura hacia la planta (Modbus/MQTT): "
                "resetear una alarma, ajustar un setpoint. La propuesta NO se "
                "ejecuta: queda pendiente de la aprobación de un operador humano "
                "con rol supervisor (Human-in-the-loop, ADR-0024). Úsalo solo "
                "cuando el diagnóstico esté claro, e incluye la justificación "
                "técnica completa para que el operador pueda decidir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "adaptador": {
                        "type": "string",
                        "description": "Protocolo destino: 'modbus' o 'mqtt'.",
                    },
                    "tag_id": {
                        "type": "string",
                        "description": "Tag escribible del catálogo de actuadores. Ej: 'reset_alarma_e117'.",
                    },
                    "valor": {
                        "type": "number",
                        "description": "Valor a escribir (debe estar dentro del límite físico del tag).",
                    },
                    "justificacion": {
                        "type": "string",
                        "description": "Diagnóstico y razón técnica de la acción propuesta.",
                    },
                },
                "required": ["adaptador", "tag_id", "valor", "justificacion"],
            },
        },
    },
]


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
    try:
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
