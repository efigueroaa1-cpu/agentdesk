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
import inspect
import json
import logging

from core.key_vault import obtener_key
from core.tools import factory

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
from core.tools.schema import TOOLS_SCHEMA  # noqa: F401  (reexport del paquete)


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
from core.tools.calc import _calcular
from core.tools.finance import _calcular_financiero
from core.tools.chile import (
    _consultar_indicadores_chile, _obtener_energia_chile, _obtener_partidos,
    _consultar_macro_chile, _buscar_empresa_cmf,
)

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


# ── Registro de herramientas en el factory (nombre -> adaptador) ──────────────
# El adaptador recibe (argumentos, contexto) y llama a la implementacion con
# el mapeo de args especifico de cada tool. Agregar una tool nueva es una
# linea aqui -- el dispatcher de abajo no cambia (elimina el riesgo de NameError
# por un import olvidado: si la funcion no existe, falla al importar este modulo,
# no en silencio en tiempo de llamada).
factory.registrar("consultar_a_otro_agente", lambda a, c: _consultar_a_otro_agente(
    a["agente_id"], a["pregunta"], origen_id=c["agente_id_clave"], user_id=c["user_id"]))
factory.registrar("proponer_comando_ot", lambda a, c: _proponer_comando_ot(
    adaptador=a["adaptador"], tag_id=a["tag_id"], valor=a["valor"],
    justificacion=a["justificacion"], agente_id=c["agente_id_clave"], user_id=c["user_id"]))
factory.registrar("buscar_web", lambda a, c: _buscar_web(
    query=a["query"], max_resultados=a.get("max_resultados", 6)))
factory.registrar("obtener_pagina", lambda a, c: _obtener_pagina(
    url=a["url"], max_chars=a.get("max_chars", 8000)))
factory.registrar("listar_archivos", lambda a, c: _listar_archivos())
factory.registrar("leer_archivo", lambda a, c: _leer_archivo(
    archivo_id=a.get("archivo_id"), max_chars=a.get("max_chars", 8000)))
factory.registrar("calcular", lambda a, c: _calcular(
    expresion=a["expresion"], descripcion=a.get("descripcion", "")))
factory.registrar("calcular_financiero", lambda a, c: _calcular_financiero(
    tipo=a["tipo"], datos=a.get("datos", {})))
factory.registrar("consultar_macro_chile", lambda a, c: _consultar_macro_chile(
    indicadores=a.get("indicadores"), historico=a.get("historico", False)))
factory.registrar("buscar_empresa_cmf", lambda a, c: _buscar_empresa_cmf(
    nombre_empresa=a.get("nombre_empresa", ""), rut=a.get("rut", "")))
factory.registrar("consultar_indicadores_chile", lambda a, c: _consultar_indicadores_chile())
factory.registrar("obtener_energia_chile", lambda a, c: _obtener_energia_chile(
    a.get("tipo", "solar_eolico")))
factory.registrar("obtener_partidos", lambda a, c: _obtener_partidos(a["consulta"]))


async def _despachar_herramienta(nombre: str, argumentos: dict, *,
                                  agente_id_clave: str = "", user_id: str = "anonimo") -> str:
    """Resolucion dinamica via factory: sin if/elif manual, sin NameError."""
    adaptador = factory.resolver(nombre)
    if adaptador is None:
        return f"Herramienta '{nombre}' no reconocida."
    try:
        resultado = adaptador(argumentos, {"agente_id_clave": agente_id_clave,
                                           "user_id": user_id})
        if inspect.isawaitable(resultado):
            resultado = await resultado
        return resultado
    except Exception as e:
        logger.error("ejecutar_herramienta '%s': %s", nombre, e)
        return f"Error ejecutando {nombre}: {e}"
