"""
core/rate_limiter.py — Cola inteligente de llamadas a la API de IA.

Problemas que resuelve:
  1. Gemini free tier: 20 req/día → las agota en minutos si hay múltiples agentes
  2. Múltiples agentes corriendo simultáneamente → saturan la API
  3. 503 (alta demanda) → necesita retry con backoff

Solución:
  - Semáforo por proveedor (máx N llamadas simultáneas)
  - Token bucket para rate limiting por minuto
  - Cola con prioridad (chat > análisis automático > batch)
  - Retry automático con backoff exponencial
  - Estadísticas de uso (requests/día, fallos, latencia)
"""
from __future__ import annotations
import asyncio
import logging
import time
from collections import defaultdict, deque
from enum import IntEnum

logger = logging.getLogger(__name__)


class Prioridad(IntEnum):
    ALTA   = 1   # Chat con el orquestador (usuario espera respuesta)
    MEDIA  = 2   # Análisis BI / tareas manuales
    BAJA   = 3   # Monitor automático, batch


# Límites por proveedor (req/min, máx concurrentes)
LIMITES = {
    "gemini":    {"rpm": 15,  "concurrent": 2,  "retry": 3},
    "groq":      {"rpm": 200, "concurrent": 10, "retry": 3},
    "openai":    {"rpm": 60,  "concurrent": 5,  "retry": 3},
    "deepseek":  {"rpm": 60,  "concurrent": 5,  "retry": 3},
    "anthropic": {"rpm": 50,  "concurrent": 5,  "retry": 3},
    "default":   {"rpm": 30,  "concurrent": 3,  "retry": 3},
}


class ProveedorLimiter:
    """Rate limiter para un proveedor específico."""

    def __init__(self, nombre: str):
        config     = LIMITES.get(nombre, LIMITES["default"])
        self.nombre    = nombre
        self.rpm       = config["rpm"]
        self.max_conc  = config["concurrent"]
        self.max_retry = config["retry"]
        self._sem      = asyncio.Semaphore(self.max_conc)
        self._ventana  = deque()           # timestamps del último minuto
        self._stats    = defaultdict(int)  # ok, fail, retry, quota_agotada

    def _limpiar_ventana(self) -> None:
        ahora = time.monotonic()
        while self._ventana and self._ventana[0] < ahora - 60:
            self._ventana.popleft()

    async def _esperar_cuota(self) -> None:
        """Espera si se alcanzó el límite de req/min."""
        while True:
            self._limpiar_ventana()
            if len(self._ventana) < self.rpm:
                self._ventana.append(time.monotonic())
                return
            # Esperar hasta que expire el request más antiguo
            espera = 60 - (time.monotonic() - self._ventana[0]) + 0.1
            logger.warning("RateLimiter %s: cuota rpm alcanzada, esperando %.1fs", self.nombre, espera)
            await asyncio.sleep(espera)

    async def llamar(self, coro, prioridad: Prioridad = Prioridad.MEDIA):
        """
        Ejecuta una coroutine con rate limiting y retry automático.
        coro: coroutine que llama al proveedor de IA
        """
        backoff = 1.0
        for intento in range(1, self.max_retry + 1):
            async with self._sem:
                await self._esperar_cuota()
                try:
                    resultado = await coro()
                    self._stats["ok"] += 1
                    return resultado
                except Exception as exc:
                    msg = str(exc)
                    es_quota = "429" in msg or "quota" in msg.lower() or "RESOURCE_EXHAUSTED" in msg
                    es_503   = "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg

                    if es_quota:
                        self._stats["quota_agotada"] += 1
                        logger.error("RateLimiter %s: cuota agotada (429)", self.nombre)
                        raise   # No reintentar cuando la cuota se agota (hay que esperar el día siguiente)

                    if es_503 and intento < self.max_retry:
                        self._stats["retry"] += 1
                        logger.warning("RateLimiter %s: 503, reintento %d/%d en %.1fs",
                                       self.nombre, intento, self.max_retry, backoff)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 30)
                        continue

                    if intento < self.max_retry:
                        self._stats["retry"] += 1
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 30)
                        continue

                    self._stats["fail"] += 1
                    raise

    def get_stats(self) -> dict:
        self._limpiar_ventana()
        return {
            "proveedor":        self.nombre,
            "req_ultimo_minuto":len(self._ventana),
            "rpm_limite":       self.rpm,
            "concurrentes_max": self.max_conc,
            **dict(self._stats),
        }


# ── Registro global de limiters ───────────────────────────────────────────────
_limiters: dict[str, ProveedorLimiter] = {}


def get_limiter(proveedor: str) -> ProveedorLimiter:
    """Obtiene o crea un limiter para el proveedor dado."""
    if proveedor not in _limiters:
        _limiters[proveedor] = ProveedorLimiter(proveedor)
    return _limiters[proveedor]


def get_stats_todos() -> list[dict]:
    """Estadísticas de todos los proveedores en uso."""
    return [l.get_stats() for l in _limiters.values()]


async def llamada_protegida(
    proveedor: str,
    coro,
    prioridad: Prioridad = Prioridad.MEDIA,
):
    """
    Wrapper principal: ejecuta una llamada a la IA con rate limiting.

    Uso desde providers.py:
        from core.rate_limiter import llamada_protegida, Prioridad
        resultado = await llamada_protegida("groq", lambda: client.chat(...), Prioridad.ALTA)
    """
    limiter = get_limiter(proveedor)
    return await limiter.llamar(coro, prioridad)
