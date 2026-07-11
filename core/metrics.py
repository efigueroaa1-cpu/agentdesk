"""
Módulo de métricas históricas para AgentDesk.

Lee logs/sistema.log (JSON estructurado), agrupa eventos por agente
y calcula latencia, tasa de éxito y tendencias.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, stdev
from core.path_manager import data_path


# ── Estructuras de datos ───────────────────────────────────────────────────────

@dataclass
class MetricasFiltro:
    nombre:      str
    ejecuciones: int   = 0
    fallos:      int   = 0
    lat_total_s: float = 0.0
    lat_max_s:   float = 0.0
    latencias:   list  = field(default_factory=list)

    @property
    def lat_promedio_s(self) -> float:
        return round(self.lat_total_s / self.ejecuciones, 4) if self.ejecuciones else 0.0

    @property
    def tasa_exito_pct(self) -> float:
        if self.ejecuciones == 0:
            return 0.0
        return round((self.ejecuciones - self.fallos) / self.ejecuciones * 100, 1)


@dataclass
class MetricasAgente:
    nombre:         str
    total_tareas:   int   = 0
    exitosas:       int   = 0
    abortadas:      int   = 0
    lat_total_s:    float = 0.0
    lat_max_s:      float = 0.0
    ultimo_run:     str   = "-"
    filtros:        dict  = field(default_factory=dict)   # nombre -> MetricasFiltro
    # Latencias cronológicas propias de este agente (punto de corte per-agente)
    _lat_todas:     list  = field(default_factory=list)

    @property
    def lat_promedio_s(self) -> float:
        return round(self.lat_total_s / self.total_tareas, 4) if self.total_tareas else 0.0

    @property
    def tasa_exito_pct(self) -> float:
        if self.total_tareas == 0:
            return 0.0
        return round(self.exitosas / self.total_tareas * 100, 1)

    @property
    def tendencia(self) -> str:
        """
        Compara la latencia promedio de la primera vs. segunda mitad
        del historial *propio* del agente.

        El punto de corte se calcula sobre _lat_todas (por agente),
        no sobre el log global, para que un agente que solo corrió
        recientemente no quede siempre con segunda_mitad vacía.

        Devuelve: 'mejora' | 'empeora' | 'estable'.
        Requiere al menos 4 mediciones (≥2 por mitad) para ser significativo.
        """
        n = len(self._lat_todas)
        if n < 4:
            return "estable"
        mid  = n // 2
        avg1 = mean(self._lat_todas[:mid])
        avg2 = mean(self._lat_todas[mid:])
        diff_pct = (avg2 - avg1) / avg1 * 100 if avg1 > 0 else 0
        if diff_pct < -5:
            return "mejora"
        if diff_pct > 5:
            return "empeora"
        return "estable"


# ── Lectura del log ────────────────────────────────────────────────────────────

def cargar_entradas_log(
    ruta: Path | str | None = None,
    max_entradas: int = 1000,
) -> list[dict]:
    """
    Lee las últimas `max_entradas` líneas JSON de sistema.log.
    Si no se pasa ruta usa data_path("logs/sistema.log") — funciona
    tanto en desarrollo como en el ejecutable PyInstaller.
    """
    ruta_path = Path(ruta) if ruta else data_path("logs/sistema.log")
    if not ruta_path.exists():
        return []
    try:
        with open(ruta_path, encoding="utf-8") as f:
            lineas = [l.strip() for l in f if l.strip().startswith("{")]
        entradas = []
        for linea in lineas[-max_entradas:]:
            try:
                entradas.append(json.loads(linea))
            except json.JSONDecodeError:
                continue
        return entradas
    except Exception:
        return []


# ── Cálculo de métricas ────────────────────────────────────────────────────────

def calcular_metricas(entradas: list[dict]) -> dict[str, MetricasAgente]:
    """
    Agrupa entradas del log por agente y calcula todas las métricas.
    Solo procesa entradas con campo 'agente' explícito.

    El historial de latencias se acumula en _lat_todas en orden cronológico
    del log global, pero el punto de corte para la tendencia se aplica
    por agente (mitad de sus propias mediciones), evitando el sesgo de
    una ventana temporal global que deja a algunos agentes siempre sin
    datos en una de las dos mitades.
    """
    metricas: dict[str, MetricasAgente] = {}

    for e in entradas:
        agente = e.get("agente", "")
        if not agente:
            continue

        if agente not in metricas:
            metricas[agente] = MetricasAgente(nombre=agente)
        m = metricas[agente]

        mensaje  = e.get("message", "").lower()
        status   = e.get("status", "")
        nivel    = e.get("level", "").upper()
        filtro   = e.get("filtro", "")
        duracion = e.get("duracion_s")
        ts       = e.get("timestamp", "")

        # ── Tarea completada con éxito ─────────────────────────────────────────
        if "tarea completada" in mensaje and status == "ok":
            m.total_tareas += 1
            m.exitosas     += 1
            if ts:
                m.ultimo_run = ts

        # ── Pipeline abortado ──────────────────────────────────────────────────
        if status == "abortado" and nivel == "ERROR":
            m.total_tareas += 1
            m.abortadas    += 1
            if ts:
                m.ultimo_run = ts

        # ── Latencia por filtro ────────────────────────────────────────────────
        if filtro and duracion is not None:
            if filtro not in m.filtros:
                m.filtros[filtro] = MetricasFiltro(nombre=filtro)
            mf = m.filtros[filtro]
            mf.ejecuciones  += 1
            mf.lat_total_s  += duracion
            mf.lat_max_s     = max(mf.lat_max_s, duracion)
            mf.latencias.append(duracion)
            if status in ("error", "timeout"):
                mf.fallos += 1

            # Acumular en el historial cronológico propio del agente
            m.lat_total_s += duracion
            m.lat_max_s    = max(m.lat_max_s, duracion)
            m._lat_todas.append(duracion)

    return metricas


def resumen_sistema(metricas: dict[str, MetricasAgente]) -> dict:
    """Calcula métricas agregadas de todo el sistema."""
    total   = sum(m.total_tareas for m in metricas.values())
    exitos  = sum(m.exitosas     for m in metricas.values())
    lat_all = [
        d for m in metricas.values()
        for mf in m.filtros.values()
        for d in mf.latencias
    ]
    return {
        "agentes":          len(metricas),
        "total_tareas":     total,
        "tasa_exito_pct":   round(exitos / total * 100, 1) if total else 0.0,
        "lat_promedio_s":   round(mean(lat_all), 4) if lat_all else 0.0,
        "lat_max_s":        round(max(lat_all), 4) if lat_all else 0.0,
        "lat_desv_std":     round(stdev(lat_all), 4) if len(lat_all) > 1 else 0.0,
    }
