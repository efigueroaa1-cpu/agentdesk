"""
core/scheduler.py — Agente de Monitoreo Automático (Opción B).

Flujo de datos:
  1. Scheduler ejecuta scrapers cada N minutos (configurable por tarea)
  2. Datos crudos → SQLite (sin pipeline — son hechos reales)
  3. Cada X ciclos, el Agente Analizador procesa los datos acumulados
  4. El análisis del agente SÍ pasa por el pipeline completo
  5. Informe guardado en SQLite + notificación WebSocket

Tareas preconfiguradas:
  - futbol_top_equipos   (cada 6 horas)
  - energia_solar_eolico (cada 1 hora)
  - energia_demanda      (cada 3 horas)
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ── Definición de tareas de monitoreo ─────────────────────────────────────────

TAREAS_DEFAULT: list[dict] = [
    {
        "id":          "futbol_top",
        "nombre":      "Fútbol — Top Equipos",
        "categoria":   "futbol",
        "icono":       "⚽",
        "intervalo_min": 360,          # cada 6 horas
        "activo":      True,
        "params":      {
            "categoria": "futbol_multiple",
            "equipos":   [
                "Real Madrid","Barcelona","Manchester City","Liverpool",
                "PSG","Bayern Munich","Colo-Colo","Chile",
            ],
        },
        "ultimo_fetch": None,
        "proxima_ejecucion": None,
        "estado":      "pendiente",    # pendiente | ejecutando | ok | error
    },
    {
        "id":          "energia_solar",
        "nombre":      "Energía Solar & Eólica Chile",
        "categoria":   "energia",
        "icono":       "☀️",
        "intervalo_min": 60,           # cada 1 hora
        "activo":      True,
        "params":      { "categoria": "energia_renovable", "dias": 7 },
        "ultimo_fetch": None,
        "proxima_ejecucion": None,
        "estado":      "pendiente",
    },
    {
        "id":          "energia_demanda",
        "nombre":      "Demanda Eléctrica Estimada",
        "categoria":   "energia",
        "icono":       "🔌",
        "intervalo_min": 180,          # cada 3 horas
        "activo":      True,
        "params":      { "categoria": "energia_demanda" },
        "ultimo_fetch": None,
        "proxima_ejecucion": None,
        "estado":      "pendiente",
    },
    {
        "id":          "indicadores_economia",
        "nombre":      "Indicadores Económicos Chile",
        "categoria":   "economia",
        "icono":       "💵",
        "intervalo_min": 30,           # cada 30 minutos
        "activo":      True,
        "params":      { "categoria": "indicadores_economia" },
        "ultimo_fetch": None,
        "proxima_ejecucion": None,
        "estado":      "pendiente",
    },
    {
        "id":          "energia_spot",
        "nombre":      "Precio Spot Eléctrico Chile",
        "categoria":   "energia",
        "icono":       "💰",
        "intervalo_min": 240,          # cada 4 horas
        "activo":      False,          # desactivado por defecto
        "params":      { "categoria": "energia_spot" },
        "ultimo_fetch": None,
        "proxima_ejecucion": None,
        "estado":      "pendiente",
    },
]

# Estado global del scheduler (en memoria + archivo JSON)
_tareas: list[dict] = []
_running = False
_orquestador_ref = None   # referencia al orquestador para análisis IA
_broadcast_fn: Callable | None = None


# ── Persistencia de configuración ─────────────────────────────────────────────

def _config_path() -> Path:
    from core.path_manager import data_path
    return data_path("scheduler_config.json")


def _cargar_config() -> list[dict]:
    """Carga configuración guardada, mezcla con defaults."""
    path = _config_path()
    if not path.exists():
        return [dict(t) for t in TAREAS_DEFAULT]
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        # Mezclar: defaults como base, saved sobreescribe id/intervalo/activo
        merged = []
        saved_map = {t["id"]: t for t in saved}
        for default in TAREAS_DEFAULT:
            t = dict(default)
            if default["id"] in saved_map:
                s = saved_map[default["id"]]
                t["activo"]       = s.get("activo",        t["activo"])
                t["intervalo_min"]= s.get("intervalo_min", t["intervalo_min"])
            merged.append(t)
        return merged
    except Exception:
        return [dict(t) for t in TAREAS_DEFAULT]


def _guardar_config() -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    save_data = [
        {"id": t["id"], "activo": t["activo"], "intervalo_min": t["intervalo_min"]}
        for t in _tareas
    ]
    path.write_text(json.dumps(save_data, indent=2), encoding="utf-8")


# ── Motor del scheduler ────────────────────────────────────────────────────────

def init_scheduler(orquestador=None, broadcast=None) -> None:
    """Inicializa el scheduler. Llamar al arrancar la API."""
    global _tareas, _orquestador_ref, _broadcast_fn
    _tareas = _cargar_config()
    _orquestador_ref = orquestador
    _broadcast_fn    = broadcast
    # Calcular próximas ejecuciones
    ahora = datetime.utcnow()
    for t in _tareas:
        t["proxima_ejecucion"] = ahora.isoformat()   # ejecutar al inicio
    logger.info("Scheduler inicializado con %d tareas", len(_tareas))


async def _ejecutar_tarea(tarea: dict) -> None:
    """Ejecuta una tarea de monitoreo: fetch → SQLite → análisis IA opcional."""
    from core.web_monitor import fetch_categoria
    from core.database   import guardar_dato_monitor, guardar_alerta

    tid    = tarea["id"]
    nombre = tarea["nombre"]
    params = tarea.get("params", {})

    tarea["estado"] = "ejecutando"
    tarea["ultimo_fetch"] = datetime.utcnow().isoformat()
    if _broadcast_fn:
        await _broadcast_fn({"tipo": "monitor_ejecutando", "tarea_id": tid, "nombre": nombre})
    logger.info("Scheduler: ejecutando '%s'", nombre)

    try:
        # ── PASO 1: Fetch de datos crudos ────────────────────────────────────
        categoria_fetch = params.get("categoria", tarea["categoria"])
        resultado = await fetch_categoria(categoria_fetch, params)

        if "error" in resultado:
            raise ValueError(resultado["error"])

        # ── PASO 2: Guardar en SQLite (datos crudos, sin pipeline) ───────────
        _persistir_resultado(tarea, resultado)

        # ── PASO 3: Análisis IA (pasa por el pipeline) ───────────────────────
        if _orquestador_ref and _orquestador_ref.agentes:
            await _analizar_con_ia(tarea, resultado)

        tarea["estado"] = "ok"
        if _broadcast_fn:
            await _broadcast_fn({
                "tipo": "monitor_completado", "tarea_id": tid,
                "nombre": nombre, "categoria": tarea["categoria"],
            })

    except Exception as exc:
        tarea["estado"] = "error"
        logger.error("Scheduler '%s': %s", nombre, exc)
        try:
            guardar_alerta(0, nombre,
                f"Error en monitoreo: {nombre}",
                str(exc)[:200], nivel="warn")
        except Exception:
            pass
        if _broadcast_fn:
            await _broadcast_fn({"tipo": "monitor_error", "tarea_id": tid, "error": str(exc)})


def _persistir_resultado(tarea: dict, resultado: dict) -> None:
    """Guarda datos crudos en SQLite según la categoría."""
    from core.database import guardar_dato_monitor
    cat = tarea["categoria"]

    try:
        if cat == "futbol":
            # resultado puede ser dict de múltiples equipos o un equipo
            equipos = resultado if isinstance(resultado, dict) and any(
                isinstance(v, dict) and "estadisticas" in v for v in resultado.values()
            ) else {resultado.get("nombre","equipo"): resultado}

            for eq_nombre, datos in equipos.items():
                if "estadisticas" not in datos:
                    continue
                st = datos["estadisticas"]
                for k, v in st.items():
                    if isinstance(v, (int, float)):
                        guardar_dato_monitor(
                            fuente_id=0, fuente_nombre=tarea["nombre"],
                            categoria="futbol", clave=f"{eq_nombre}/{k}",
                            valor=str(v), valor_numerico=float(v),
                        )

        elif cat == "energia":
            # Solar
            if "solar" in resultado:
                for k, v in resultado["solar"].items():
                    if isinstance(v, (int, float)):
                        guardar_dato_monitor(0, tarea["nombre"], "energia",
                            f"solar/{k}", str(v), float(v), "W/m²")
            # Eólico
            if "eolico" in resultado:
                for k, v in resultado["eolico"].items():
                    if isinstance(v, (int, float)):
                        guardar_dato_monitor(0, tarea["nombre"], "energia",
                            f"eolico/{k}", str(v), float(v), "km/h")
            # Temperatura
            if "temperatura" in resultado:
                for k, v in resultado["temperatura"].items():
                    if isinstance(v, (int, float)):
                        guardar_dato_monitor(0, tarea["nombre"], "energia",
                            f"temperatura/{k}", str(v), float(v), "°C")
            # Precio spot
            if "precio_prom_usd_mwh" in resultado and resultado["precio_prom_usd_mwh"]:
                guardar_dato_monitor(0, tarea["nombre"], "energia",
                    "spot/precio_prom_usd_mwh",
                    str(resultado["precio_prom_usd_mwh"]),
                    float(resultado["precio_prom_usd_mwh"]), "USD/MWh")

        elif cat == "economia":
            for campo, unidad in [("dolar","CLP"), ("uf","CLP"), ("euro","CLP"), ("ipc","%")]:
                valor = resultado.get(campo)
                if valor is not None:
                    guardar_dato_monitor(
                        fuente_id=0, fuente_nombre=tarea["nombre"],
                        categoria="economia", clave=campo,
                        valor=str(valor), valor_numerico=float(valor), unidad=unidad,
                    )

    except Exception as exc:
        logger.warning("_persistir_resultado '%s': %s", tarea["id"], exc)


async def _analizar_con_ia(tarea: dict, datos_crudos: dict) -> None:
    """
    Análisis IA de los datos monitoreados.
    Este análisis SÍ pasa por el pipeline de guardrails.
    """
    if not _orquestador_ref or not _orquestador_ref.agentes:
        return

    # Elegir agente según categoría
    agente = None
    cat = tarea["categoria"]
    for ag in _orquestador_ref.agentes.values():
        area = (ag.area or "").lower()
        if cat == "energia" and area in ("electricidad","tecnología","general","general"):
            agente = ag; break
        if cat == "futbol" and area in ("general","datos","marketing"):
            agente = ag; break
    if agente is None:
        agente = next(iter(_orquestador_ref.agentes.values()))

    # Construir resumen de los datos para el agente
    resumen_datos = json.dumps(datos_crudos, ensure_ascii=False, indent=2)[:8000]
    prompt_datos  = (
        f"Datos recolectados automáticamente del monitor de {tarea['nombre']}:\n\n"
        f"{resumen_datos}\n\n"
        f"Analiza estos datos, detecta tendencias importantes y genera un resumen ejecutivo."
    )

    try:
        # chat_libre usa el agente en modo conversacional
        # (sin pipeline, para el resumen inicial)
        analisis = await agente.chat_libre(prompt_datos)

        # Guardar análisis en SQLite
        from core.database import guardar_dato_monitor
        guardar_dato_monitor(
            fuente_id=0, fuente_nombre=f"Análisis IA — {tarea['nombre']}",
            categoria=f"{tarea['categoria']}_analisis",
            clave=f"analisis_{tarea['id']}",
            valor=analisis[:2000],
            metadata={"agente": agente.nombre, "ts": datetime.utcnow().isoformat()},
        )

        if _broadcast_fn:
            await _broadcast_fn({
                "tipo":    "monitor_analisis_listo",
                "tarea_id": tarea["id"],
                "agente":   agente.nombre,
                "resumen":  analisis[:300],
            })
        logger.info("Análisis IA completado para '%s' por agente '%s'",
                    tarea["nombre"], agente.nombre)
    except Exception as exc:
        logger.warning("_analizar_con_ia '%s': %s", tarea["id"], exc)


async def _loop_scheduler() -> None:
    """Loop principal del scheduler — corre en background."""
    global _running
    _running = True
    logger.info("Scheduler: loop iniciado")

    while _running:
        ahora = datetime.utcnow()
        for tarea in _tareas:
            if not tarea.get("activo"):
                continue
            prox = tarea.get("proxima_ejecucion")
            if not prox:
                continue
            try:
                prox_dt = datetime.fromisoformat(prox)
            except Exception:
                prox_dt = ahora

            if ahora >= prox_dt:
                # Calcular próxima ejecución ANTES de ejecutar
                tarea["proxima_ejecucion"] = (
                    ahora + timedelta(minutes=tarea["intervalo_min"])
                ).isoformat()
                # Ejecutar en background sin bloquear el loop
                asyncio.create_task(_ejecutar_tarea(tarea))

        await asyncio.sleep(60)   # revisar cada minuto

    logger.info("Scheduler: loop detenido")


# ── API pública ────────────────────────────────────────────────────────────────

def get_tareas() -> list[dict]:
    """Estado actual de todas las tareas."""
    return [
        {
            "id":           t["id"],
            "nombre":       t["nombre"],
            "categoria":    t["categoria"],
            "icono":        t["icono"],
            "intervalo_min":t["intervalo_min"],
            "activo":       t["activo"],
            "estado":       t["estado"],
            "ultimo_fetch": t["ultimo_fetch"],
            "proxima_ejecucion": t["proxima_ejecucion"],
        }
        for t in _tareas
    ]


def actualizar_tarea(tarea_id: str, activo: bool | None = None,
                     intervalo_min: int | None = None) -> dict | None:
    """Actualiza configuración de una tarea."""
    for t in _tareas:
        if t["id"] == tarea_id:
            if activo is not None:      t["activo"] = activo
            if intervalo_min is not None:
                t["intervalo_min"] = max(1, intervalo_min)
            if activo:   # al activar, programar ejecución inmediata
                t["proxima_ejecucion"] = datetime.utcnow().isoformat()
                t["estado"] = "pendiente"
            _guardar_config()
            return get_tareas()
    return None


async def ejecutar_ahora(tarea_id: str) -> bool:
    """Dispara una tarea inmediatamente."""
    for t in _tareas:
        if t["id"] == tarea_id:
            asyncio.create_task(_ejecutar_tarea(t))
            return True
    return False


def start_scheduler(orquestador=None, broadcast=None) -> asyncio.Task:
    """Arrancar el scheduler como tarea asyncio."""
    init_scheduler(orquestador, broadcast)
    return asyncio.create_task(_loop_scheduler())


def stop_scheduler() -> None:
    global _running
    _running = False
