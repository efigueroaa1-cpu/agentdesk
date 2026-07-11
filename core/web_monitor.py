"""
core/web_monitor.py — Motor de monitoreo web con scrapers sin API key.

Fuentes implementadas (todas gratuitas, sin registro):
  - TheSportsDB   → Fútbol: equipos, resultados, tendencias
  - Coordinador Eléctrico Nacional (Chile) → Energía eléctrica
  - Open-Meteo   → Energía renovable / clima
"""
from __future__ import annotations
import asyncio
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ── Cliente HTTP base (stdlib pura — sin aiohttp) ─────────────────────────────
HEADERS = {
    "User-Agent": "AgentDesk/1.0 (research tool)",
    "Accept":     "application/json",
}

def _sync_get(url: str, params: dict | None = None) -> Any:
    """GET síncrono con urllib (sin dependencias externas)."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        ct   = resp.headers.get("Content-Type","")
        return json.loads(body) if "json" in ct else body

async def _get(url: str, params: dict | None = None) -> Any:
    """GET asíncrono usando executor para no bloquear el event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_get, url, params)


# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 1 — FÚTBOL (TheSportsDB — 100% gratuito, sin API key)
# ══════════════════════════════════════════════════════════════════════════════
BASE_SDB = "https://www.thesportsdb.com/api/v1/json/3"

EQUIPOS_PRESET = [
    "Colo-Colo", "Universidad de Chile", "Universidad Católica",
    "Chile", "Argentina", "Brasil", "España", "Francia", "Alemania",
    "Real Madrid", "Barcelona", "Manchester City", "Liverpool",
    "PSG", "Bayern Munich", "Juventus",
]

# Catálogo completo de ligas con sus IDs en TheSportsDB
LIGAS_CATALOGO: list[dict] = [
    # ── Mundial y Selecciones ──────────────────────────────────────────────────
    { "id":"4411", "nombre":"FIFA World Cup 2026",       "pais":"USA/Mex/Can","grupo":"Mundial" },
    { "id":"4429", "nombre":"Copa América",              "pais":"CONMEBOL",  "grupo":"Mundial" },
    { "id":"4443", "nombre":"UEFA Euro 2024",            "pais":"UEFA",      "grupo":"Mundial" },
    # ── Sudamérica ─────────────────────────────────────────────────────────────
    { "id":"4442", "nombre":"Primera División Chile",    "pais":"Chile",     "grupo":"Sudamérica" },
    { "id":"4406", "nombre":"Liga Argentina",            "pais":"Argentina", "grupo":"Sudamérica" },
    { "id":"4351", "nombre":"Brasileirão Série A",       "pais":"Brasil",    "grupo":"Sudamérica" },
    { "id":"4415", "nombre":"Copa Libertadores",         "pais":"CONMEBOL",  "grupo":"Sudamérica" },
    # ── Europa ─────────────────────────────────────────────────────────────────
    { "id":"4328", "nombre":"Premier League",            "pais":"Inglaterra","grupo":"Europa" },
    { "id":"4335", "nombre":"La Liga",                   "pais":"España",    "grupo":"Europa" },
    { "id":"4331", "nombre":"Bundesliga",                "pais":"Alemania",  "grupo":"Europa" },
    { "id":"4332", "nombre":"Serie A",                   "pais":"Italia",    "grupo":"Europa" },
    { "id":"4334", "nombre":"Ligue 1",                   "pais":"Francia",   "grupo":"Europa" },
    { "id":"4480", "nombre":"UEFA Champions League",     "pais":"UEFA",      "grupo":"Europa" },
    # ── Otras ──────────────────────────────────────────────────────────────────
    { "id":"4346", "nombre":"MLS",                       "pais":"USA",       "grupo":"Otros" },
    { "id":"4340", "nombre":"Liga MX",                   "pais":"México",    "grupo":"Otros" },
]

LIGAS_PRESET = { l["nombre"]: l["id"] for l in LIGAS_CATALOGO }


async def buscar_equipo(nombre: str) -> dict | None:
    """Busca un equipo por nombre en TheSportsDB."""
    try:
        data = await _get(f"{BASE_SDB}/searchteams.php", params={"t": nombre})
        teams = (data or {}).get("teams") or []
        return teams[0] if teams else None
    except Exception as e:
        logger.error("buscar_equipo '%s': %s", nombre, e)
        return None


async def get_ultimos_partidos(id_equipo: str) -> list[dict]:
    """Últimos N partidos de un equipo."""
    try:
        data = await _get(f"{BASE_SDB}/eventslast.php", params={"id": id_equipo})
        return (data or {}).get("results") or []
    except Exception as e:
        logger.error("get_ultimos_partidos %s: %s", id_equipo, e)
        return []


async def get_proximos_partidos(id_equipo: str) -> list[dict]:
    """Próximos partidos de un equipo."""
    try:
        data = await _get(f"{BASE_SDB}/eventsnext.php", params={"id": id_equipo})
        return (data or {}).get("events") or []
    except Exception as e:
        logger.error("get_proximos_partidos %s: %s", id_equipo, e)
        return []


def _calcular_estadisticas(partidos: list[dict], id_equipo: str) -> dict:
    """Calcula V/E/D, racha, goles a favor y en contra."""
    v = e = d = gf = gc = 0
    racha = []

    for p in partidos:
        local    = p.get("idHomeTeam") == id_equipo
        goles_loc= int(p.get("intHomeScore") or 0)
        goles_vis= int(p.get("intAwayScore") or 0)
        mis_goles   = goles_loc if local else goles_vis
        sus_goles   = goles_vis if local else goles_loc
        gf += mis_goles
        gc += sus_goles
        if mis_goles > sus_goles:   v += 1; racha.append("V")
        elif mis_goles == sus_goles: e += 1; racha.append("E")
        else:                        d += 1; racha.append("D")

    total = v + e + d
    return {
        "partidos":  total,
        "victorias": v,
        "empates":   e,
        "derrotas":  d,
        "pct_victoria": round(v/total*100, 1) if total else 0,
        "pct_empate":   round(e/total*100, 1) if total else 0,
        "pct_derrota":  round(d/total*100, 1) if total else 0,
        "goles_favor":  gf,
        "goles_contra": gc,
        "diferencia_goles": gf - gc,
        "racha_ultimos_5": "".join(racha[-5:]),
        "tendencia": _tendencia(racha[-5:]),
    }


def _tendencia(racha: list[str]) -> str:
    if not racha: return "sin datos"
    score = sum(3 if r=="V" else 1 if r=="E" else 0 for r in racha)
    if score >= 12: return "excelente"
    if score >= 8:  return "buena"
    if score >= 5:  return "regular"
    return "mala"


async def fetch_futbol_equipo(nombre: str) -> dict:
    """
    Obtiene datos completos de un equipo:
    info, últimos partidos, estadísticas, próximos partidos.
    """
    equipo = await buscar_equipo(nombre)
    if not equipo:
        return {"error": f"Equipo '{nombre}' no encontrado en TheSportsDB"}

    id_eq = equipo.get("idTeam")
    ultimos   = await get_ultimos_partidos(id_eq)
    proximos  = await get_proximos_partidos(id_eq)
    stats     = _calcular_estadisticas(ultimos, id_eq)

    # Formatear últimos partidos para legibilidad
    partidos_fmt = []
    for p in ultimos[:10]:
        fecha = p.get("dateEvent","?")
        local = p.get("strHomeTeam","?")
        visit = p.get("strAwayTeam","?")
        gl    = p.get("intHomeScore","?")
        gv    = p.get("intAwayScore","?")
        partidos_fmt.append(f"{fecha}: {local} {gl}-{gv} {visit}")

    return {
        "nombre":       equipo.get("strTeam"),
        "pais":         equipo.get("strCountry"),
        "liga":         equipo.get("strLeague"),
        "fundado":      equipo.get("intFormedYear"),
        "estadio":      equipo.get("strStadium"),
        "descripcion":  (equipo.get("strDescriptionES") or equipo.get("strDescriptionEN",""))[:500],
        "estadisticas": stats,
        "ultimos_partidos": partidos_fmt,
        "proximos_partidos": [
            f"{p.get('dateEvent','?')}: {p.get('strHomeTeam','?')} vs {p.get('strAwayTeam','?')}"
            for p in proximos[:5]
        ],
        "fuente": "TheSportsDB (thesportsdb.com)",
        "ts": datetime.utcnow().isoformat(),
    }


async def fetch_futbol_multiple(equipos: list[str]) -> dict:
    """Fetch paralelo de múltiples equipos."""
    tareas = [fetch_futbol_equipo(eq) for eq in equipos]
    resultados = await asyncio.gather(*tareas, return_exceptions=True)
    return {
        eq: (r if not isinstance(r, Exception) else {"error": str(r)})
        for eq, r in zip(equipos, resultados)
    }


async def fetch_liga_tabla(liga_id: str, temporada: str = "2024-2025") -> dict:
    """
    Obtiene tabla de posiciones de una liga.
    Usa lookuptable de TheSportsDB (no requiere API key).
    """
    try:
        # Probar temporadas en orden de más reciente a más antigua
        tabla = []
        for t in ["2025-2026", "2026", "2024-2025", "2025", "2023-2024", temporada]:
            try:
                data = await _get(f"{BASE_SDB}/lookuptable.php", params={"l": liga_id, "s": t})
                tabla = (data or {}).get("table") or []
                if tabla:
                    break
            except Exception:
                continue

        equipos_tabla = []
        for fila in tabla:
            equipos_tabla.append({
                "posicion":  int(fila.get("intRank",        0) or 0),
                "equipo":    fila.get("strTeam",            ""),
                "pj":        int(fila.get("intPlayed",      0) or 0),
                "victorias": int(fila.get("intWin",         0) or 0),
                "empates":   int(fila.get("intDraw",        0) or 0),
                "derrotas":  int(fila.get("intLoss",        0) or 0),
                "gf":        int(fila.get("intGoalsFor",    0) or 0),
                "gc":        int(fila.get("intGoalsAgainst",0) or 0),
                "diferencia":int(fila.get("intGoalDifference",0) or 0),
                "puntos":    int(fila.get("intPoints",      0) or 0),
                "forma":     fila.get("strForm",            "") or "",
                "pct_victoria": round(
                    int(fila.get("intWin",0) or 0) /
                    max(int(fila.get("intPlayed",1) or 1),1)*100, 1
                ),
            })
        return equipos_tabla
    except Exception as e:
        logger.error("fetch_liga_tabla %s: %s", liga_id, e)
        return []


async def fetch_liga_partidos_recientes(liga_id: str) -> list[dict]:
    """Últimos partidos jugados en una liga."""
    try:
        data = await _get(f"{BASE_SDB}/eventspastleague.php", params={"id": liga_id})
        events = (data or {}).get("events") or []
        return [{
            "fecha":  e.get("dateEvent","?"),
            "local":  e.get("strHomeTeam","?"),
            "visita": e.get("strAwayTeam","?"),
            "gl":     e.get("intHomeScore","?"),
            "gv":     e.get("intAwayScore","?"),
            "ronda":  e.get("strRound",""),
        } for e in events[-20:]]
    except Exception as e:
        logger.error("fetch_liga_partidos %s: %s", liga_id, e)
        return []


async def fetch_liga_proximos(liga_id: str) -> list[dict]:
    """Próximos partidos de una liga."""
    try:
        data = await _get(f"{BASE_SDB}/eventsnextleague.php", params={"id": liga_id})
        events = (data or {}).get("events") or []
        return [{
            "fecha":  e.get("dateEvent","?"),
            "hora":   e.get("strTime",""),
            "local":  e.get("strHomeTeam","?"),
            "visita": e.get("strAwayTeam","?"),
            "ronda":  e.get("strRound",""),
        } for e in events[:15]]
    except Exception as e:
        logger.error("fetch_liga_proximos %s: %s", liga_id, e)
        return []


async def fetch_futbol_liga_completo(liga_id: str, liga_nombre: str = "") -> dict:
    """
    Datos completos de una liga:
    tabla de posiciones + partidos recientes + próximos + estadísticas.
    """
    tabla, recientes, proximos = await asyncio.gather(
        fetch_liga_tabla(liga_id),
        fetch_liga_partidos_recientes(liga_id),
        fetch_liga_proximos(liga_id),
        return_exceptions=True,
    )
    if isinstance(tabla, Exception):    tabla    = []
    if isinstance(recientes, Exception):recientes= []
    if isinstance(proximos, Exception): proximos = []

    # Estadísticas agregadas de la liga
    if tabla:
        max_pts  = max((e["puntos"] for e in tabla), default=0)
        prom_gol = round(sum(e["gf"] for e in tabla) / max(len(tabla),1), 1)
        lider    = tabla[0]["equipo"] if tabla else "?"
        top_gols = max(tabla, key=lambda x:x["gf"], default={}).get("equipo","?")
    else:
        max_pts = max_gf = prom_gol = 0
        lider = top_gols = "?"

    return {
        "liga_id":   liga_id,
        "liga":      liga_nombre,
        "temporada": "2024-2025",
        "equipos_tabla": tabla,
        "partidos_recientes": recientes,
        "proximos_partidos":  proximos,
        "estadisticas_liga": {
            "equipos":       len(tabla),
            "lider":         lider,
            "max_puntos":    max_pts,
            "equipo_mas_goles": top_gols,
            "total_goles_marcados": sum(e["gf"] for e in tabla),
            "promedio_goles_equipo": prom_gol,
        },
        "fuente": "TheSportsDB (thesportsdb.com)",
        "ts":     datetime.utcnow().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER 2 — ENERGÍA ELÉCTRICA (Open-Meteo + datos públicos)
# ══════════════════════════════════════════════════════════════════════════════
BASE_METEO = "https://api.open-meteo.com/v1"
BASE_POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"

# Coordenadas Chile central (Santiago) para datos de energía
COORDS_SANTIAGO = {"lat": -33.45, "lon": -70.67}

# Coordinador Eléctrico Nacional — datos públicos
URL_COORDINADOR = "https://www.coordinador.cl/mercados/documentos/costos-marginales/costo-marginal-real/"


async def fetch_energia_renovable(dias: int = 7) -> dict:
    """
    Datos de energía solar y eólica para Chile central.
    Usa Open-Meteo (100% gratuito, sin API key).
    """
    fecha_fin   = datetime.utcnow().date()
    fecha_ini   = fecha_fin - timedelta(days=dias)

    params = {
        "latitude":   COORDS_SANTIAGO["lat"],
        "longitude":  COORDS_SANTIAGO["lon"],
        "hourly":     "shortwave_radiation,windspeed_10m",
        "start_date": str(fecha_ini),
        "end_date":   str(fecha_fin),
        "timezone":   "America/Santiago",
    }
    try:
        data    = await _get(f"{BASE_METEO}/forecast", params=params)
        hourly = data.get("hourly", {})
        rad    = hourly.get("shortwave_radiation", [])
        viento = hourly.get("windspeed_10m", [])

        rad_v   = [v for v in rad   if v is not None and v > 0]
        viento_v= [v for v in viento if v is not None]

        # Potencial solar (W/m²) y eólico (km/h)
        solar_prom  = round(sum(rad_v)/len(rad_v),   1) if rad_v   else 0
        solar_max   = round(max(rad_v),               1) if rad_v   else 0
        viento_prom = round(sum(viento_v)/len(viento_v),1) if viento_v else 0
        viento_max  = round(max(viento_v),             1) if viento_v else 0

        # Tendencia: comparar primera mitad vs segunda mitad
        mid = len(rad_v)//2
        tend_solar = "↑ creciendo" if mid and sum(rad_v[mid:])>sum(rad_v[:mid]) else "↓ decreciendo"

        return {
            "periodo":       f"{fecha_ini} → {fecha_fin}",
            "zona":          "Santiago, Chile",
            "solar": {
                "promedio_wm2":  solar_prom,
                "maximo_wm2":    solar_max,
                "tendencia":     tend_solar,
                "potencial":     "Alto" if solar_prom > 300 else "Medio" if solar_prom > 150 else "Bajo",
            },
            "eolico": {
                "velocidad_prom_kmh": viento_prom,
                "velocidad_max_kmh":  viento_max,
                "potencial": "Alto" if viento_prom > 25 else "Medio" if viento_prom > 15 else "Bajo",
            },
            "recomendacion_renovable": (
                "Alta generación solar esperada — buen momento para análisis de instalaciones FV"
                if solar_prom > 250 else
                "Generación solar moderada — evaluar complementar con eólico"
            ),
            "fuente": "Open-Meteo (open-meteo.com)",
            "ts": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("fetch_energia_renovable: %s", e)
        return {"error": str(e)}


async def fetch_precios_spot_electricos() -> dict:
    """
    Precio spot del sistema eléctrico chileno (SEN).
    Fuente: Coordinador Eléctrico Nacional (datos públicos).
    """
    try:
        # Los precios spot se publican en archivos CSV/Excel públicos
        # Usamos la API REST pública del Coordinador
        url = "https://sipub.coordinador.cl/api/v1/recursos/costos_marginales_reales/"
        params = {
            "format":    "json",
            "fecha__gte": (datetime.utcnow()-timedelta(days=7)).strftime("%Y-%m-%d"),
            "limit":      50,
        }
        data = await _get(url, params=params)
        resultados = data.get("results", []) if isinstance(data, dict) else []

        if not resultados:
            # Fallback: datos representativos del mercado (si API no responde)
            return {
                "nota": "API Coordinador no disponible — usando datos de referencia",
                "precio_referencia_usd_mwh": 85.0,
                "fuente": "coordinador.cl (datos pueden requerir acceso directo)",
                "ts": datetime.utcnow().isoformat(),
            }

        precios = [float(r.get("costo_marginal_real", 0)) for r in resultados if r.get("costo_marginal_real")]
        return {
            "registros":     len(resultados),
            "precio_prom_usd_mwh": round(sum(precios)/len(precios), 2) if precios else None,
            "precio_max":    round(max(precios), 2) if precios else None,
            "precio_min":    round(min(precios), 2) if precios else None,
            "tendencia":     "↑ al alza" if len(precios)>1 and precios[-1]>precios[0] else "↓ a la baja",
            "ultimo_registro": resultados[0] if resultados else None,
            "fuente": "Coordinador Eléctrico Nacional (sipub.coordinador.cl)",
            "ts": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("fetch_precios_spot: %s", e)
        return {"error": str(e), "ts": datetime.utcnow().isoformat()}


async def fetch_demanda_electrica() -> dict:
    """
    Estimación de demanda eléctrica basada en temperatura (correlación directa).
    Mayor temperatura → mayor uso de climatización → mayor demanda.
    """
    try:
        params = {
            "latitude":   COORDS_SANTIAGO["lat"],
            "longitude":  COORDS_SANTIAGO["lon"],
            "hourly":     "temperature_2m,apparent_temperature",
            "forecast_days": 3,
            "timezone":   "America/Santiago",
        }
        data   = await _get(f"{BASE_METEO}/forecast", params=params)
        hourly = data.get("hourly", {})
        temps = [t for t in (hourly.get("temperature_2m") or []) if t is not None]

        hoy   = temps[:24]
        mana  = temps[24:48]
        pasad = temps[48:72]

        def prom(lst): return round(sum(lst)/len(lst),1) if lst else None
        def demanda_est(t): return "Alta" if t and t>28 else "Media" if t and t>18 else "Baja"

        return {
            "temperatura": {
                "hoy_prom_c":    prom(hoy),
                "manana_prom_c": prom(mana),
                "pasado_prom_c": prom(pasad),
            },
            "demanda_estimada": {
                "hoy":    demanda_est(prom(hoy)),
                "manana": demanda_est(prom(mana)),
                "pasado_manana": demanda_est(prom(pasad)),
            },
            "alerta": (
                "Temperatura alta prevista — posible peak de demanda eléctrica"
                if prom(mana) and prom(mana) > 30 else
                "Demanda eléctrica dentro de parámetros normales"
            ),
            "fuente": "Open-Meteo (forecast meteorológico)",
            "ts": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("fetch_demanda_electrica: %s", e)
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# FETCH COMPLETO por categoría
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_indicadores_economia() -> dict:
    """
    Obtiene UF, dólar, euro, IPC del Banco Central (mindicador.cl).
    Verifica umbrales configurados y crea MonitorAlerta si se supera alguno.
    """
    try:
        data = await _get("https://mindicador.cl/api")
        if not isinstance(data, dict):
            return {"error": "Respuesta inválida de mindicador.cl"}

        uf    = float(data.get("uf",    {}).get("valor", 0) or 0)
        dolar = float(data.get("dolar", {}).get("valor", 0) or 0)
        euro  = float(data.get("euro",  {}).get("valor", 0) or 0)
        ipc   = float(data.get("ipc",   {}).get("valor", 0) or 0)
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

        resultado = {
            "uf": uf, "dolar": dolar, "euro": euro, "ipc": ipc, "fecha": fecha,
        }

        # Verificar umbrales y emitir alertas
        _verificar_umbrales_economia(resultado)
        return resultado

    except Exception as exc:
        logger.warning("fetch_indicadores_economia: %s", exc)
        return {"error": str(exc)}


def _verificar_umbrales_economia(indicadores: dict) -> None:
    """Crea MonitorAlerta si algún indicador cruza un umbral configurado."""
    try:
        from core.path_manager import data_path
        import json as _json
        from core.database import guardar_alerta

        cfg_path = data_path("alertas_config.json")
        if not cfg_path.exists():
            return
        cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
        umbrales = cfg.get("umbrales", {})

        mapeo = {
            "dolar_max": ("dolar", "Dólar USA superó umbral máximo",   "critico"),
            "dolar_min": ("dolar", "Dólar USA bajó del umbral mínimo", "warn"),
            "uf_max":    ("uf",    "UF superó umbral máximo",          "warn"),
            "ipc_max":   ("ipc",   "IPC superó umbral máximo",         "critico"),
        }

        for clave, (campo, titulo, nivel) in mapeo.items():
            if clave not in umbrales:
                continue
            val_actual  = indicadores.get(campo, 0)
            val_umbral  = umbrales[clave]
            supera      = val_actual > val_umbral if "max" in clave else val_actual < val_umbral
            if supera:
                guardar_alerta(
                    fuente_id=0, fuente_nombre="Banco Central Chile",
                    titulo=titulo,
                    descripcion=(f"{campo.upper()} actual: ${val_actual:,.2f} CLP  "
                                 f"| Umbral: ${val_umbral:,.2f} CLP  "
                                 f"| Fecha: {indicadores.get('fecha','')}"),
                    nivel=nivel,
                )
                logger.info("Alerta económica generada: %s = %s", clave, val_actual)

    except Exception as exc:
        logger.warning("_verificar_umbrales_economia: %s", exc)


async def fetch_categoria(categoria: str, params: dict | None = None) -> dict:
    """
    Punto de entrada unificado para cualquier categoría de datos.
    categoria: "futbol_equipo", "futbol_multiple", "energia_renovable",
               "energia_spot", "energia_demanda", "indicadores_economia"
    """
    p = params or {}
    if categoria == "futbol_equipo":
        return await fetch_futbol_equipo(p.get("nombre", "Colo-Colo"))
    if categoria == "futbol_multiple":
        equipos = p.get("equipos", EQUIPOS_PRESET[:6])
        return await fetch_futbol_multiple(equipos)
    if categoria == "futbol_liga":
        return await fetch_futbol_liga_completo(
            p.get("liga_id", "4328"),
            p.get("nombre", "Premier League"),
        )
    if categoria == "energia_renovable":
        return await fetch_energia_renovable(p.get("dias", 7))
    if categoria == "energia_spot":
        return await fetch_precios_spot_electricos()
    if categoria == "energia_demanda":
        return await fetch_demanda_electrica()
    if categoria == "indicadores_economia":
        return await fetch_indicadores_economia()
    return {"error": f"Categoría '{categoria}' no reconocida"}
