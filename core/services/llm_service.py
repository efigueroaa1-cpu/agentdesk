"""
core/services/llm_service.py — Resiliencia de Inteligencia (Fase 8, ADR-0006).

Cadena de fallback automática con Circuit Breaker por proveedor:

    Groq → Gemini → OpenAI → MockProvider (siempre responde)

- Un proveedor que falla (errores 5xx/red) o excede la latencia máxima
  (30 s) abre su circuito: queda 'inactivo' durante un periodo de enfriamiento
  y la cadena salta al siguiente de forma transparente para el agente.
- Tras el enfriamiento el circuito pasa a semi-abierto: se le permite UN
  intento; si responde, se cierra (proveedor sano de nuevo).
- El eslabón final es el MockProvider (determinista, sin red): la inteligencia
  degrada, pero el sistema NUNCA deja de responder — 99.9% de uptime de
  inteligencia por diseño, no por fe en la infalibilidad de un proveedor.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Modelo por defecto de cada eslabón de la cadena
CADENA_FALLBACK: list[tuple[str, str]] = [
    ("groq",   "groq:llama-3.3-70b-versatile"),
    ("gemini", "gemini:models/gemini-2.5-flash"),
    ("openai", "openai:gpt-4o-mini"),
    ("mock",   "mock:agentdesk-demo"),
]

LATENCIA_MAX_S   = 30.0    # más de esto = proveedor 'colgado' → abrir circuito
ENFRIAMIENTO_S   = 120.0   # tiempo que un circuito abierto permanece inactivo
FALLOS_PARA_ABRIR = 2      # fallos consecutivos que abren el circuito


@dataclass
class CircuitBreaker:
    """Estado del circuito de UN proveedor (cerrado/abierto/semi-abierto)."""
    fallos_consecutivos: int   = 0
    abierto_hasta:       float = 0.0    # time.monotonic() de reapertura

    def disponible(self) -> bool:
        """Cerrado, o abierto pero ya en ventana semi-abierta (1 intento)."""
        return time.monotonic() >= self.abierto_hasta

    def registrar_exito(self) -> None:
        self.fallos_consecutivos = 0
        self.abierto_hasta       = 0.0

    def registrar_fallo(self) -> None:
        self.fallos_consecutivos += 1
        if self.fallos_consecutivos >= FALLOS_PARA_ABRIR:
            self.abierto_hasta = time.monotonic() + ENFRIAMIENTO_S


class LlmService:
    """
    Generación de texto resiliente. El generador por proveedor es inyectable
    (tests con dobles); por defecto usa core.providers.generate.
    """

    def __init__(
        self,
        generador: Callable[[str, str, float, int], Awaitable[str]] | None = None,
        cadena: list[tuple[str, str]] | None = None,
        latencia_max_s: float = LATENCIA_MAX_S,
    ):
        if generador is None:
            from core.providers import generate as _generate
            generador = _generate
        self._generar        = generador
        self._cadena         = cadena or list(CADENA_FALLBACK)
        self._latencia_max_s = latencia_max_s
        self._circuitos: dict[str, CircuitBreaker] = {
            proveedor: CircuitBreaker() for proveedor, _ in self._cadena
        }
        from collections import deque
        self._latencias: dict[str, deque] = {p: deque(maxlen=20) for p, _ in self._cadena}
        self._ultimo_error: dict[str, str] = {}

    def estado_circuitos(self) -> dict:
        """Diagnóstico para el Módulo Diagnóstico: estado OPEN/CLOSED,
        fallos, latencias recientes y último error por proveedor."""
        ahora = time.monotonic()
        estado = {}
        for p, cb in self._circuitos.items():
            lats = list(self._latencias.get(p, []))
            estado[p] = {
                "estado": "CLOSED" if cb.disponible() else "OPEN",
                "activo": cb.disponible(),
                "fallos_consecutivos": cb.fallos_consecutivos,
                "reabre_en_s": max(0, round(cb.abierto_hasta - ahora, 1)),
                "latencia_prom_s": round(sum(lats) / len(lats), 2) if lats else None,
                "latencia_ultima_s": round(lats[-1], 2) if lats else None,
                "muestras": len(lats),
                "ultimo_error": self._ultimo_error.get(p, ""),
            }
        return estado

    async def generar(self, prompt: str, temperatura: float = 0.4,
                      prioridad: int = 2) -> dict:
        """
        Recorre la cadena de fallback hasta obtener respuesta.
        Retorna {"texto", "proveedor", "modelo", "intentos", "degradado"}.
        Solo lanza si TODOS los eslabones fallan (con mock al final, no ocurre
        salvo bug interno: el mock no usa red).
        """
        intentos: list[str] = []
        for proveedor, modelo in self._cadena:
            cb = self._circuitos[proveedor]
            if not cb.disponible():
                intentos.append(f"{proveedor}:circuito-abierto")
                continue

            t0 = time.monotonic()
            try:
                texto = await asyncio.wait_for(
                    self._generar(modelo, prompt, temperatura, prioridad),
                    timeout=self._latencia_max_s,
                )
                cb.registrar_exito()
                self._latencias[proveedor].append(time.monotonic() - t0)
                self._ultimo_error.pop(proveedor, None)
                if intentos:
                    logger.warning(
                        "LLM_FALLBACK: respondio '%s' tras saltar %s",
                        proveedor, intentos,
                    )
                return {
                    "texto":     texto,
                    "proveedor": proveedor,
                    "modelo":    modelo,
                    "intentos":  intentos + [f"{proveedor}:ok"],
                    "degradado": proveedor == "mock",
                }
            except asyncio.TimeoutError:
                cb.registrar_fallo()
                self._ultimo_error[proveedor] = f"latencia>{self._latencia_max_s:.0f}s"
                intentos.append(f"{proveedor}:latencia>{self._latencia_max_s:.0f}s")
                logger.warning("CIRCUIT_BREAKER: '%s' excedio latencia (%.0fs) — "
                               "fallos=%d", proveedor, self._latencia_max_s,
                               cb.fallos_consecutivos)
            except Exception as exc:
                cb.registrar_fallo()
                self._ultimo_error[proveedor] = f"{type(exc).__name__}: {str(exc)[:120]}"
                intentos.append(f"{proveedor}:{type(exc).__name__}")
                logger.warning("CIRCUIT_BREAKER: '%s' fallo (%s) — fallos=%d "
                               "dur=%.1fs", proveedor, exc,
                               cb.fallos_consecutivos, time.monotonic() - t0)

        raise RuntimeError(f"Cadena LLM agotada sin respuesta: {intentos}")


# Instancia por defecto del proceso (los circuitos son estado compartido)
llm_service = LlmService()
