"""
core/services/resource_guard.py — Circuit Breaker de Concurrencia y
Declaración de Costo de Recursos (Fase 21, ADR-0019).

Dos responsabilidades relacionadas, ambas sobre la misma pregunta ("¿este
host puede absorber otra tarea pesada ahora mismo?"):

  1. `puede_admitir_tarea()`: límite DINÁMICO de tareas concurrentes basado
     en la carga real de CPU/RAM del proceso host (vía `psutil`), no un
     contador fijo. Si el host ya está por encima del umbral crítico,
     rechaza nuevas tareas pesadas en vez de apilarlas y agravar la
     saturación — mismo principio que un CircuitBreaker de proveedor LLM
     (ADR-0006/0017), aplicado a recursos de máquina en vez de a un API
     externa. Zero-Default (ADR-0016): si `psutil` no está instalado, el
     límite se degrada a "siempre admite" con una advertencia UNA sola vez
     — la ausencia de la librería opcional no debe tumbar el sistema.

  2. `costo_recursos(cpu, memoria)`: decorador que documenta, en el propio
     código, el costo estimado de CPU/memoria de una función pesada
     (generación de PDFs, embeddings 3D, backups, reduce de Map-Reduce).
     Es metadata declarativa, no un límite — el Guardián ([SCALE-LIMITS],
     scripts/gate.py) exige su presencia en toda función que ya pasa por
     `queue_service.ejecutar_pesado()`/`encolar()`.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

NIVELES_COSTO = {"bajo", "medio", "alto"}

# Umbrales del circuit breaker de concurrencia. Configurables porque el
# umbral "correcto" depende del hardware real de la planta/host — no hay
# un valor universal (Zero-Default: la ausencia usa este default razonable).
CPU_MAX_PORCENTAJE_DEFECTO = 90.0
MEM_MAX_PORCENTAJE_DEFECTO = 90.0

_avisado_sin_psutil = False


class RecursosAgotadosError(RuntimeError):
    """El host está por encima del umbral crítico de CPU/RAM — tarea rechazada."""


def _umbral(nombre_env: str, defecto: float) -> float:
    valor = os.environ.get(nombre_env, "").strip()
    if not valor:
        return defecto
    try:
        pct = float(valor)
    except ValueError:
        logger.warning("RESOURCE_GUARD: %s=%r invalido (no es numero) — usando default %.1f",
                       nombre_env, valor, defecto)
        return defecto
    if not (0 < pct <= 100):
        logger.warning("RESOURCE_GUARD: %s=%.1f invalido (debe estar en (0,100]) — usando default %.1f",
                       nombre_env, pct, defecto)
        return defecto
    return pct


def carga_actual() -> dict:
    """
    {'cpu_pct', 'mem_pct', 'psutil_disponible'} — lectura instantánea de la
    carga del host. Best-effort: sin psutil, retorna 0.0/0.0 con el flag en
    False (nunca lanza).
    """
    global _avisado_sin_psutil
    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=None)
        mem_pct = psutil.virtual_memory().percent
        try:
            from core.metrics_prometheus import actualizar_carga_host
            actualizar_carga_host(cpu_pct, mem_pct)
        except Exception as exc:
            logger.warning("RESOURCE_GUARD: metricas Prometheus no actualizadas (%s)", exc)
        return {"cpu_pct": cpu_pct, "mem_pct": mem_pct, "psutil_disponible": True}
    except ImportError:
        if not _avisado_sin_psutil:
            logger.warning(
                "RESOURCE_GUARD: psutil no instalado — el circuit breaker de "
                "concurrencia degrada a 'siempre admite' (sin visibilidad de carga real)."
            )
            _avisado_sin_psutil = True
        return {"cpu_pct": 0.0, "mem_pct": 0.0, "psutil_disponible": False}


def puede_admitir_tarea() -> bool:
    """
    True si el host tiene margen para absorber otra tarea pesada. Sin
    psutil, siempre True (degradación documentada en `carga_actual()`).
    """
    carga = carga_actual()
    if not carga["psutil_disponible"]:
        return True
    cpu_max = _umbral("AGENTDESK_CPU_MAX_PCT", CPU_MAX_PORCENTAJE_DEFECTO)
    mem_max = _umbral("AGENTDESK_MEM_MAX_PCT", MEM_MAX_PORCENTAJE_DEFECTO)
    admite = carga["cpu_pct"] < cpu_max and carga["mem_pct"] < mem_max
    if not admite:
        logger.warning(
            "AUDITORIA_SEGURIDAD: circuito de concurrencia ABIERTO — "
            "cpu=%.1f%% (max %.1f%%) mem=%.1f%% (max %.1f%%) — tareas pesadas "
            "nuevas suspendidas para proteger la estabilidad del host",
            carga["cpu_pct"], cpu_max, carga["mem_pct"], mem_max,
        )
        try:
            from core.metrics_prometheus import registrar_circuito_concurrencia_abierto
            registrar_circuito_concurrencia_abierto()
        except Exception as exc:
            logger.warning("RESOURCE_GUARD: metricas Prometheus no actualizadas (%s)", exc)
    return admite


def costo_recursos(cpu: str, memoria: str) -> Callable:
    """
    Decorador declarativo: `@costo_recursos(cpu="alto", memoria="medio")`.
    No modifica el comportamiento de la función — solo adjunta metadata
    (`fn.costo_recursos`) que el Guardián [SCALE-LIMITS] exige encontrar en
    toda función que se despacha vía `queue_service.ejecutar_pesado()`/
    `encolar()`. `cpu`/`memoria` deben ser uno de NIVELES_COSTO.
    """
    if cpu not in NIVELES_COSTO or memoria not in NIVELES_COSTO:
        raise ValueError(
            f"costo_recursos: cpu/memoria deben ser uno de {NIVELES_COSTO} "
            f"(recibido cpu={cpu!r}, memoria={memoria!r})"
        )

    def decorador(fn: Callable) -> Callable:
        fn.costo_recursos = {"cpu": cpu, "memoria": memoria}
        return fn

    return decorador
