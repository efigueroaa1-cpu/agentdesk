"""
core/services/analytics_service.py — Métricas y tendencias (ADR-0003).

Lógica de analytics extraída de core/api.py: KPIs del dashboard, tendencias
por regresión lineal, estadísticas históricas por agente, lectura de logs
estructurados y embeddings 3D. Sin FastAPI: funciones puras sobre SQLite,
disco y config; los objetos de runtime (orquestador) llegan por parámetro.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime as _dt, timedelta as _td

from core.timeutil import utcnow

logger = logging.getLogger(__name__)


def _agentes_config() -> dict:
    """config.json → dict {id: agente} tolerante a lista o dict."""
    from core.config_loader import load_config
    cfg  = load_config()
    _raw = cfg.get("agents", cfg.get("agentes", []))
    if isinstance(_raw, list):
        return {a["id"]: a for a in _raw if isinstance(a, dict) and "id" in a}
    if isinstance(_raw, dict):
        return _raw
    return {}


def calcular_tendencia(valores: list[float]) -> str:
    """
    Tendencia de una serie por regresión lineal mínima:
    'mejorando', 'estable' o 'empeorando'. Para tasa_exito la pendiente
    positiva mejora; para latencia el llamador invierte el resultado.
    """
    n = len(valores)
    if n < 3:
        return "estable"
    xs  = list(range(n))
    x_m = sum(xs) / n
    y_m = sum(valores) / n
    num = sum((xs[i] - x_m) * (valores[i] - y_m) for i in range(n))
    den = sum((xs[i] - x_m) ** 2 for i in range(n))
    if den == 0:
        return "estable"
    slope  = num / den
    rango  = max(valores) - min(valores)
    umbral = max(rango * 0.05, 1.0)
    if slope > umbral / n:
        return "mejorando"
    if slope < -umbral / n:
        return "empeorando"
    return "estable"


def _serie_diaria(dias_data: dict) -> list[dict]:
    """{dia: {ok, fail, lats}} → puntos ordenados con tasa y latencia promedio."""
    puntos = []
    for dia, d in sorted(dias_data.items()):
        total    = d["ok"] + d["fail"]
        lats     = d["lats"]
        prom_lat = round(sum(lats) / len(lats), 3) if lats else None
        puntos.append({
            "fecha":      dia,
            "total":      total,
            "exitosas":   d["ok"],
            "fallidas":   d["fail"],
            "tasa_exito": round(d["ok"] / total * 100, 1) if total else 0,
            "latencia_s": prom_lat,
        })
    return puntos


def _resumen_de(dias_data: dict, puntos: list[dict], lat_prom) -> dict:
    total_ok   = sum(d["ok"]   for d in dias_data.values())
    total_fail = sum(d["fail"] for d in dias_data.values())
    total_all  = total_ok + total_fail

    tend_exito = calcular_tendencia([p["tasa_exito"] for p in puntos])
    lats_serie = [p["latencia_s"] for p in puntos if p["latencia_s"] is not None]
    if len(lats_serie) >= 3:
        # Invertir: pendiente negativa de latencia = "mejorando" (menos tiempo)
        tend_lat = {"mejorando": "empeorando", "empeorando": "mejorando",
                    "estable": "estable"}[calcular_tendencia(lats_serie)]
    else:
        tend_lat = "sin datos"

    return {
        "total_ejecuciones":  total_all,
        "tasa_exito_global":  round(total_ok / total_all * 100, 1) if total_all else 0,
        "latencia_prom_s":    lat_prom,
        "tendencia":          tend_exito,
        "tendencia_latencia": tend_lat,
    }


async def tendencias_agente(agente_id: str, dias: int = 30) -> dict:
    """
    Tendencias de rendimiento de un agente en los últimos N días.
    Primero intenta con Ejecucion (pipeline formal); si no hay datos usa las
    conversaciones de chat como proxy de actividad.
    """
    from core.database import get_session, Ejecucion

    desde = utcnow() - _td(days=dias)

    # ── Intento 1: datos de ejecuciones del pipeline ──────────────────────
    with get_session() as s:
        exec_rows = (
            s.query(Ejecucion)
            .filter(Ejecucion.agente_id == agente_id, Ejecucion.ts >= desde)
            .order_by(Ejecucion.ts.asc())
            .all()
        )

    if exec_rows:
        dias_data: dict = {}
        for r in exec_rows:
            dia = r.ts.strftime("%Y-%m-%d") if r.ts else "?"
            if dia not in dias_data:
                dias_data[dia] = {"ok": 0, "fail": 0, "lats": []}
            if r.exitoso:
                dias_data[dia]["ok"] += 1
            else:
                dias_data[dia]["fail"] += 1
            if r.duracion_s and r.duracion_s > 0:
                dias_data[dia]["lats"].append(r.duracion_s)

        puntos     = _serie_diaria(dias_data)
        todas_lats = [r.duracion_s for r in exec_rows if r.duracion_s and r.duracion_s > 0]
        lat_prom   = round(sum(todas_lats) / len(todas_lats), 3) if todas_lats else None
        return {
            "agente_id": agente_id,
            "dias":      dias,
            "puntos":    puntos,
            "fuente":    "pipeline",
            "resumen":   _resumen_de(dias_data, puntos, lat_prom),
        }

    # ── Intento 2: fallback a conversaciones de chat ──────────────────────
    try:
        from core.memory import Conversacion as _Conv, Mensaje as _Msg
        with get_session() as s:
            convs = (
                s.query(_Conv)
                .filter(_Conv.agente_id == agente_id, _Conv.ts_inicio >= desde)
                .all()
            )
            if not convs:
                return {"puntos": [], "resumen": None}

            conv_ids = [c.id for c in convs]
            all_msgs = (
                s.query(_Msg)
                .filter(_Msg.conversacion_id.in_(conv_ids))
                .order_by(_Msg.ts.asc())
                .all()
            )

        msgs_by_conv: dict = defaultdict(list)
        for m in all_msgs:
            msgs_by_conv[m.conversacion_id].append(m)

        dias_data2: dict = {}
        for conv in convs:
            msgs = msgs_by_conv.get(conv.id, [])
            if not msgs:
                continue  # ignorar sesiones vacías
            dia = conv.ts_inicio.strftime("%Y-%m-%d")
            if dia not in dias_data2:
                dias_data2[dia] = {"ok": 0, "fail": 0, "lats": []}

            user_msgs  = [m for m in msgs if m.rol == "usuario"]
            agent_msgs = [m for m in msgs if m.rol == "agente"]

            if agent_msgs:
                dias_data2[dia]["ok"] += 1
                if user_msgs and user_msgs[0].ts and agent_msgs[0].ts:
                    lat = (agent_msgs[0].ts - user_msgs[0].ts).total_seconds()
                    if 0 < lat < 300:
                        dias_data2[dia]["lats"].append(lat)
            else:
                dias_data2[dia]["fail"] += 1

        if not dias_data2:
            return {"puntos": [], "resumen": None}

        puntos2 = _serie_diaria(dias_data2)
        lats2   = [p["latencia_s"] for p in puntos2 if p["latencia_s"] is not None]
        lat_prom2 = round(sum(lats2) / len(lats2), 3) if lats2 else None
        return {
            "agente_id": agente_id,
            "dias":      dias,
            "puntos":    puntos2,
            "fuente":    "conversaciones",
            "resumen":   _resumen_de(dias_data2, puntos2, lat_prom2),
        }
    except Exception:
        return {"puntos": [], "resumen": None}


async def agentes_stats(dias: int = 90) -> dict:
    """
    Estadísticas históricas de todos los agentes en el formato que usa
    localStorage ('agentdesk-agent-stats-v2') para pre-poblar el Dashboard
    de Rendimiento al cargar la app.
    """
    stats: dict = {}
    for ag_id in _agentes_config():
        try:
            data    = await tendencias_agente(ag_id, dias=dias)
            resumen = data.get("resumen")
            if not resumen:
                continue
            total = resumen.get("total_ejecuciones", 0)
            tasa  = resumen.get("tasa_exito_global", 100)
            ok    = round(total * tasa / 100)
            fail  = total - ok
            # ultimasTareas con mínimo 2 entradas para que el frontend lo procese
            n_ok   = max(ok, 2) if ok > 0 else 0
            n_fail = max(fail, 1) if fail > 0 else 0
            puntos = data.get("puntos", [])
            stats[ag_id] = {
                "ok":            ok,
                "fail":          fail,
                "ultimasTareas": (["ok"] * min(n_ok, 3) + ["fail"] * min(n_fail, 2))[-5:],
                "ultima_ts":     puntos[-1].get("fecha") if puntos else None,
            }
        except Exception:
            continue
    return {"stats": stats}


def dashboard_datos(agente_id: str = "", dias: int = 30) -> dict:
    """Métricas y series para el dashboard de Analytics (SQLite + reportes)."""
    from core.path_manager import REPORTES_DIR

    dias        = max(7, min(365, int(dias)))
    agentes_cfg = _agentes_config()

    agente_info: dict = {}
    if agente_id and agente_id in agentes_cfg:
        a = agentes_cfg[agente_id]
        agente_info = {
            "id":     agente_id,
            "nombre": a.get("nombre", agente_id),
            "area":   a.get("area", "General"),
            "modelo": a.get("modelo", ""),
        }

    # ── Métricas SQLite ───────────────────────────────────────────────────
    total_sesiones = total_mensajes = 0
    actividad_raw: list = []
    horaria_raw: list   = []
    try:
        from core.database import get_session
        from core.memory import Conversacion, Mensaje
        from sqlalchemy import func as _func

        with get_session() as s:
            q = s.query(Conversacion)
            if agente_id:
                q = q.filter(Conversacion.agente_id == agente_id)
            total_sesiones = q.count()

            qm = s.query(Mensaje)
            if agente_id:
                qm = qm.filter(Mensaje.agente_id == agente_id)
            total_mensajes = qm.count()

            hace_n = utcnow() - _td(days=dias)

            qa = (
                s.query(
                    _func.date(Mensaje.ts).label("dia"),
                    _func.count(Mensaje.id).label("n"),
                )
                .filter(Mensaje.ts >= hace_n)
            )
            if agente_id:
                qa = qa.filter(Mensaje.agente_id == agente_id)
            actividad_raw = qa.group_by(_func.date(Mensaje.ts)).all()

            # Heatmap horario: [weekday 0-6] × [hour 0-23]
            qh = (
                s.query(
                    _func.strftime("%w", Mensaje.ts).label("dow"),
                    _func.strftime("%H", Mensaje.ts).label("hora"),
                    _func.count(Mensaje.id).label("n"),
                )
                .filter(Mensaje.ts >= hace_n)
            )
            if agente_id:
                qh = qh.filter(Mensaje.agente_id == agente_id)
            horaria_raw = qh.group_by("dow", "hora").all()

    except Exception as _e:
        logger.warning("dashboard_datos DB: %s", _e)

    # Matriz 7×24 (SQLite %w: 0=Dom … 6=Sáb)
    actividad_horaria = [[0] * 24 for _ in range(7)]
    for row in horaria_raw:
        try:
            actividad_horaria[int(row.dow)][int(row.hora)] = int(row.n)
        except Exception:
            pass

    # ── Reportes en disco ─────────────────────────────────────────────────
    rdir = REPORTES_DIR
    todos_pdf = sorted(rdir.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True) if rdir.exists() else []
    nombre_clave = (agente_info.get("nombre") or "").replace(" ", "_")[:12].lower()
    filtrados = [r for r in todos_pdf if nombre_clave and nombre_clave in r.stem.lower()] or todos_pdf

    reportes_recientes = [
        {
            "nombre":    r.name,
            "fecha":     _dt.fromtimestamp(r.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
            "tamano_kb": round(r.stat().st_size / 1024, 1),
        }
        for r in filtrados[:12]
    ]

    # ── Series temporales ─────────────────────────────────────────────────
    hoy      = utcnow().date()
    act_dict = {str(row.dia): row.n for row in actividad_raw}
    actividad_serie = [
        {"fecha": (hoy - _td(days=i)).strftime("%d/%m"),
         "mensajes": act_dict.get(str(hoy - _td(days=i)), 0)}
        for i in range(dias - 1, -1, -1)
    ]

    rep_por_dia: dict[str, int] = {}
    for r in filtrados:
        d = _dt.fromtimestamp(r.stat().st_mtime).strftime("%d/%m")
        rep_por_dia[d] = rep_por_dia.get(d, 0) + 1
    reportes_serie = [
        {"fecha": a["fecha"], "reportes": rep_por_dia.get(a["fecha"], 0)}
        for a in actividad_serie
    ]

    return {
        "agente": agente_info,
        "dias":   dias,
        "agentes_disponibles": [
            {"id": k, "nombre": v.get("nombre", k), "area": v.get("area", "")}
            for k, v in agentes_cfg.items()
        ],
        "kpis": {
            "sesiones": total_sesiones,
            "mensajes": total_mensajes,
            "reportes": len(filtrados),
        },
        "actividad_serie":    actividad_serie,
        "reportes_serie":     reportes_serie,
        "actividad_horaria":  actividad_horaria,
        "reportes_recientes": reportes_recientes,
    }


def leer_logs(n: int = 100, nivel: str = "all") -> dict:
    """Últimas N entradas del log estructurado sistema.log como JSON."""
    import json as _json
    from core.path_manager import data_path
    log_path = data_path("logs/sistema.log")
    if not log_path.exists():
        return {"entradas": [], "total": 0}
    try:
        lineas   = log_path.read_text(encoding="utf-8").splitlines()
        entradas = []
        for l in lineas:
            l = l.strip()
            if not l.startswith("{"):
                continue
            try:
                e = _json.loads(l)
                if nivel != "all" and e.get("level", "").upper() != nivel.upper():
                    continue
                entradas.append(e)
            except Exception:
                continue
        entradas = entradas[-n:]
        return {"entradas": list(reversed(entradas)), "total": len(entradas)}
    except Exception as e:
        return {"entradas": [], "total": 0, "error": str(e)}


def embeddings_3d(orquestador) -> dict:
    """
    Embeddings semánticos reales (TF-IDF + PCA): agentes similares quedan
    cercanos en 3D. `orquestador` puede ser None (usa config.json).
    """
    from core.embeddings import calcular_embeddings
    from core.database import get_historial

    agentes_lista = []
    if orquestador:
        for aid, ag in orquestador.agentes.items():
            agentes_lista.append({
                "id":          aid,
                "nombre":      ag.nombre,
                "area":        getattr(ag, "area", "General"),
                "prompt_base": getattr(ag, "prompt_base", ""),
                "modelo":      ag.modelo,
                "temperatura": getattr(ag, "temperatura", 0.4),
                "idioma":      getattr(ag, "idioma", "español"),
            })

    if not agentes_lista:
        try:
            from core.config_loader import load_config
            agentes_lista = load_config().get("agents", [])
        except Exception:
            pass

    hist_por_agente = {}
    try:
        for ag in agentes_lista:
            hist_por_agente[ag["id"]] = get_historial(agente_id=ag["id"], limit=10)
    except Exception:
        pass

    puntos = calcular_embeddings(agentes_lista, hist_por_agente)
    return {
        "puntos":  puntos,
        "total":   len(puntos),
        "metodo":  "TF-IDF + PCA (semántico real)" if len(agentes_lista) > 1 else "distribución circular",
        "agentes": len(agentes_lista),
    }
