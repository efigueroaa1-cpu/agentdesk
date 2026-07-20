"""
core/services/llm_service.py — Resiliencia de Inteligencia (Fase 8, ADR-0006;
extendido en Fase 19, ADR-0017; Fase 20, ADR-0018).

Cadena de fallback automática con Circuit Breaker por proveedor:

    Groq → Gemini → OpenAI → Ollama (local) → MockProvider (siempre responde)

- Un proveedor que falla (errores 5xx/red) o excede la latencia máxima
  (30 s) abre su circuito: queda 'inactivo' durante un periodo de enfriamiento
  y la cadena salta al siguiente de forma transparente para el agente.
- Tras el enfriamiento el circuito pasa a semi-abierto: se le permite UN
  intento; si responde, se cierra (proveedor sano de nuevo).
- El eslabón final es el MockProvider (determinista, sin red): la inteligencia
  degrada, pero el sistema NUNCA deja de responder — 99.9% de uptime de
  inteligencia por diseño, no por fe en la infalibilidad de un proveedor.

Fase 19 (ADR-0017), hallazgo real: esta cadena existía desde la Fase 8 pero
`core/orchestrator.py` (el chat/tarea real de cada agente) llamaba a
`core.providers.generate` DIRECTO, sin pasar por aquí — la resiliencia
estaba implementada pero desconectada del camino real. `generar()` ahora
acepta `modelo_preferido` (el modelo configurado del agente): la cadena
SIEMPRE lo intenta primero — el fallback nunca anula la elección explícita
del usuario, solo la protege — y cae al resto de la cadena estándar si
falla. También propaga el conteo de tokens (real cuando el proveedor lo
expone, estimado si no) para la auditoría FinOps.

Fase 20 (ADR-0018), Soberanía de Datos: se agrega `ollama` al final de la
cadena de proveedores reales, ANTES del mock — entre "toda la nube caída"
y "degradar a respuestas deterministas sin inteligencia real" hay un
tercer estado: un modelo local (Ollama/LM Studio, `core.providers._ollama`)
que sigue siendo inteligencia real, solo que sin salir a internet. `mock`
se conserva como último eslabón porque sigue cumpliendo un rol distinto
(garantiza respuesta SIEMPRE, incluso sin ningún servidor local corriendo,
y es el determinismo que usa toda la suite de tests) — Ollama no lo
reemplaza, se inserta antes.

`CircuitBreaker` gana `abierto_desde`: el instante (monotonic) en que
empezó la racha ACTUAL de indisponibilidad continua de un proveedor (se
resetea a 0 en cuanto responde con éxito una vez). `abierto_hasta` por sí
solo no alcanza para saber "cuánto lleva caído": con `ENFRIAMIENTO_S=120`
un circuito nunca muestra más de 2 minutos de ventana cerrada de una sola
vez, aunque sean 5 fallos seguidos del mismo problema de fondo
arrastrándose 10 minutos. `alert_service` (Fase 20) usa `abierto_desde`
para el SLO de "circuito abierto > 5 minutos".
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# ── Clasificación de 429 por ventana de cuota (2026-07-20) ────────────────────
# Un 429 "tokens/solicitudes POR MINUTO" (TPM/RPM) se recupera en segundos —
# vale la pena un reintento corto. Un 429 "POR DIA" (TPD/RPD) no se recupera
# en segundos ni minutos (el propio proveedor suele indicar "retry in Nm") —
# reintentar de inmediato es puro desperdicio: la MISMA llamada vuelve a
# fallar con el mismo error. Groq y Gemini declaran la ventana explícitamente
# en el mensaje de error (verificado en vivo, 2026-07-20).
_PATRON_LIMITE_DIA    = re.compile(r"per\s*day|PerDay|diari[oa]", re.I)
_PATRON_LIMITE_MINUTO = re.compile(r"per\s*minute|PerMinute", re.I)


def _es_limite_por_minuto(mensaje: str) -> bool:
    """True solo si el 429 declara ventana POR MINUTO (recuperable en segundos)."""
    return bool(_PATRON_LIMITE_MINUTO.search(mensaje)) and not _PATRON_LIMITE_DIA.search(mensaje)


REINTENTOS_LIMITE_MINUTO = 2      # máximo de reintentos cortos por 429 de TPM/RPM
ESPERA_LIMITE_MINUTO_S   = 5.0    # espera entre reintentos (no aplica a límites diarios)

# Modelo por defecto de cada eslabón de la cadena
CADENA_FALLBACK: list[tuple[str, str]] = [
    ("groq",   "groq:llama-3.3-70b-versatile"),
    ("gemini", "gemini:models/gemini-2.5-flash"),
    ("openai", "openai:gpt-4o-mini"),
    ("ollama", "ollama:llama3.2"),   # Fase 20, ADR-0018: soberanía de datos local
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
    # Fase 20 (ADR-0018): inicio de la racha ACTUAL de indisponibilidad
    # continua (0.0 = sano). Distinto de abierto_hasta -- ver docstring del
    # módulo. Lo usa alert_service para el SLO de "circuito abierto >5min".
    abierto_desde:        float = 0.0

    def disponible(self) -> bool:
        """Cerrado, o abierto pero ya en ventana semi-abierta (1 intento)."""
        return time.monotonic() >= self.abierto_hasta

    def registrar_exito(self) -> None:
        self.fallos_consecutivos = 0
        self.abierto_hasta       = 0.0
        self.abierto_desde       = 0.0

    def registrar_fallo(self) -> None:
        self.fallos_consecutivos += 1
        if self.fallos_consecutivos >= FALLOS_PARA_ABRIR:
            self.abierto_hasta = time.monotonic() + ENFRIAMIENTO_S
            if not self.abierto_desde:   # solo marca el INICIO de la racha
                self.abierto_desde = time.monotonic()


class LlmService:
    """
    Generación de texto resiliente. El generador por proveedor es inyectable
    (tests con dobles); por defecto usa core.providers.generate.
    """

    def __init__(
        self,
        generador: Callable[[str, str, float, int], Awaitable[str]] | None = None,
        generador_con_uso: Callable[[str, str, float, int], Awaitable[dict]] | None = None,
        cadena: list[tuple[str, str]] | None = None,
        latencia_max_s: float = LATENCIA_MAX_S,
    ):
        if generador_con_uso is not None:
            self._generar_con_uso = generador_con_uso
        elif generador is not None:
            # Compatibilidad con dobles de test anteriores a Fase 19, que
            # inyectan un generador string-only (sin conteo de tokens).
            async def _adaptar(model_id: str, prompt: str, temperatura: float,
                               prioridad: int) -> dict:
                texto = await generador(model_id, prompt, temperatura, prioridad)
                entrada, salida = len(prompt) // 4, len(texto) // 4
                return {"texto": texto, "tokens_entrada": entrada,
                        "tokens_salida": salida, "tokens_total": entrada + salida,
                        "tokens_exactos": False}
            self._generar_con_uso = _adaptar
        else:
            from core.providers import generate_con_uso as _generate_con_uso
            self._generar_con_uso = _generate_con_uso

        self._cadena         = cadena or list(CADENA_FALLBACK)
        self._latencia_max_s = latencia_max_s
        self._circuitos: dict[str, CircuitBreaker] = {
            proveedor: CircuitBreaker() for proveedor, _ in self._cadena
        }
        from collections import deque
        self._latencias: dict[str, deque] = {p: deque(maxlen=20) for p, _ in self._cadena}
        self._ultimo_error: dict[str, str] = {}

    def disponible(self, proveedor: str) -> bool:
        """
        True si el circuito de `proveedor` esta cerrado (o en semi-abierto).
        Fase 19: permite a un llamador que NO pasa por generar() (ej. el
        loop de tool-calling nativo de chat_con_herramientas, que habla
        directo con el SDK del proveedor por las herramientas) consultar
        el mismo circuito compartido antes de intentar una llamada costosa.
        Un proveedor sin circuito propio (nunca visto) se considera
        disponible -- no hay evidencia de que este fallando.
        """
        cb = self._circuitos.get(proveedor)
        return cb.disponible() if cb else True

    def registrar_fallo(self, proveedor: str, motivo: str = "") -> None:
        """
        Reporta un fallo al circuito compartido desde fuera de generar()
        (Fase 19) -- mismo circuito que ve /diagnostico/llm y que protege
        la cadena de fallback. Crea el circuito si el proveedor es nuevo.
        """
        if proveedor not in self._circuitos:
            from collections import deque
            self._circuitos[proveedor] = CircuitBreaker()
            self._latencias[proveedor] = deque(maxlen=20)
        self._circuitos[proveedor].registrar_fallo()
        if motivo:
            self._ultimo_error[proveedor] = motivo
        logger.warning("CIRCUIT_BREAKER: '%s' fallo reportado externamente (%s)",
                       proveedor, motivo)

    def registrar_exito(self, proveedor: str) -> None:
        """Reporta un exito al circuito compartido desde fuera de generar() (Fase 19)."""
        cb = self._circuitos.get(proveedor)
        if cb:
            cb.registrar_exito()

    def _cadena_efectiva(self, modelo_preferido: str | None) -> list[tuple[str, str]]:
        """
        Sin modelo_preferido: la cadena estandar (groq->gemini->openai->mock).
        Con modelo_preferido (el modelo configurado del agente): ese
        proveedor se intenta SIEMPRE primero -- el fallback nunca anula la
        eleccion explicita del usuario, solo la protege -- y el resto de la
        cadena estandar sigue disponible como red de seguridad si falla.
        Si el proveedor preferido no tenia circuito propio (no esta en la
        cadena estandar, ej. anthropic), se le crea uno nuevo aqui mismo.
        """
        if not modelo_preferido:
            return self._cadena
        from core.providers import parse_model_id
        proveedor_pref, _ = parse_model_id(modelo_preferido)
        if proveedor_pref not in self._circuitos:
            from collections import deque
            self._circuitos[proveedor_pref] = CircuitBreaker()
            self._latencias[proveedor_pref] = deque(maxlen=20)
        resto = [(p, m) for p, m in self._cadena if p != proveedor_pref]
        return [(proveedor_pref, modelo_preferido)] + resto

    def resetear_circuito(self, proveedor: str | None = None) -> list[str]:
        """
        Reset forzado (operacional) de Circuit Breakers: cierra el circuito
        YA, sin esperar el enfriamiento de 120s. Caso real: se corrigió la
        API key de un proveedor y no tiene sentido seguir saltándolo.

        Con `proveedor` resetea solo ese circuito; sin argumento, todos.
        Devuelve la lista de proveedores cuyo circuito estaba ABIERTO y
        quedó cerrado (para el log de auditoría del endpoint). Un proveedor
        desconocido devuelve lista vacía, jamás lanza.
        """
        objetivo = (
            [proveedor] if proveedor is not None else list(self._circuitos)
        )
        reseteados: list[str] = []
        for p in objetivo:
            cb = self._circuitos.get(p)
            if cb is None:
                continue
            if not cb.disponible():
                reseteados.append(p)
            cb.registrar_exito()
            self._ultimo_error.pop(p, None)
        if reseteados:
            logger.warning("CIRCUIT_BREAKER: reset forzado de %s", reseteados)
        return reseteados

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
                # Fase 20 (ADR-0018): hace cuanto arranco la racha ACTUAL de
                # indisponibilidad continua (0 si el circuito esta sano). Lo
                # usa alert_service para el SLO "circuito abierto >5min".
                "abierto_desde_hace_s": round(ahora - cb.abierto_desde, 1) if cb.abierto_desde else 0,
                "latencia_prom_s": round(sum(lats) / len(lats), 2) if lats else None,
                "latencia_ultima_s": round(lats[-1], 2) if lats else None,
                "muestras": len(lats),
                "ultimo_error": self._ultimo_error.get(p, ""),
            }
        return estado

    async def generar(self, prompt: str, temperatura: float = 0.4,
                      prioridad: int = 2, modelo_preferido: str | None = None) -> dict:
        """
        Recorre la cadena de fallback hasta obtener respuesta.

        modelo_preferido (Fase 19): si se especifica (ej. el modelo
        configurado del agente que llama), su proveedor se intenta SIEMPRE
        primero, protegido por su propio circuito -- ver _cadena_efectiva().

        Retorna {"texto", "proveedor", "modelo", "intentos", "degradado",
        "tokens_entrada", "tokens_salida", "tokens_total", "tokens_exactos"}.
        Solo lanza si TODOS los eslabones fallan (con mock al final, no ocurre
        salvo bug interno: el mock no usa red).
        """
        intentos: list[str] = []
        for proveedor, modelo in self._cadena_efectiva(modelo_preferido):
            cb = self._circuitos[proveedor]
            if not cb.disponible():
                intentos.append(f"{proveedor}:circuito-abierto")
                continue

            t0 = time.monotonic()
            reintento_minuto = 0
            while True:
                try:
                    resultado_gen = await asyncio.wait_for(
                        self._generar_con_uso(modelo, prompt, temperatura, prioridad),
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
                        "texto":     resultado_gen["texto"],
                        "proveedor": proveedor,
                        "modelo":    modelo,
                        "intentos":  intentos + [f"{proveedor}:ok"],
                        "degradado": proveedor == "mock",
                        "tokens_entrada": resultado_gen.get("tokens_entrada"),
                        "tokens_salida":  resultado_gen.get("tokens_salida"),
                        "tokens_total":   resultado_gen.get("tokens_total"),
                        "tokens_exactos": resultado_gen.get("tokens_exactos", False),
                    }
                except asyncio.TimeoutError:
                    cb.registrar_fallo()
                    self._ultimo_error[proveedor] = f"latencia>{self._latencia_max_s:.0f}s"
                    intentos.append(f"{proveedor}:latencia>{self._latencia_max_s:.0f}s")
                    logger.warning("CIRCUIT_BREAKER: '%s' excedio latencia (%.0fs) — "
                                   "fallos=%d", proveedor, self._latencia_max_s,
                                   cb.fallos_consecutivos)
                    break
                except Exception as exc:
                    mensaje = str(exc)
                    # 429 persistente (2026-07-20): un limite POR MINUTO se
                    # recupera en segundos — vale un reintento corto DENTRO
                    # del mismo proveedor, sin gastar el circuito ni saltar
                    # de inmediato al siguiente eslabon de la cadena. Un
                    # limite POR DIA (Groq/Gemini TPD/RPD) NO se recupera en
                    # segundos: reintentar solo repetiria el mismo error.
                    if (_es_limite_por_minuto(mensaje)
                            and reintento_minuto < REINTENTOS_LIMITE_MINUTO):
                        reintento_minuto += 1
                        logger.warning(
                            "LLM_RETRY: '%s' 429 por-minuto (intento %d/%d) — "
                            "esperando %.0fs antes de reintentar: %s",
                            proveedor, reintento_minuto, REINTENTOS_LIMITE_MINUTO,
                            ESPERA_LIMITE_MINUTO_S, mensaje[:160],
                        )
                        await asyncio.sleep(ESPERA_LIMITE_MINUTO_S)
                        continue
                    cb.registrar_fallo()
                    self._ultimo_error[proveedor] = f"{type(exc).__name__}: {mensaje[:120]}"
                    intentos.append(f"{proveedor}:{type(exc).__name__}")
                    logger.warning("CIRCUIT_BREAKER: '%s' fallo (%s) — fallos=%d "
                                   "dur=%.1fs", proveedor, exc,
                                   cb.fallos_consecutivos, time.monotonic() - t0)
                    break

        raise RuntimeError(f"Cadena LLM agotada sin respuesta: {intentos}")


# Instancia por defecto del proceso (los circuitos son estado compartido)
llm_service = LlmService()
