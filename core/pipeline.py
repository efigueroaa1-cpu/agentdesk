"""
Guardrails de ejecución para el pipeline de agentes.

Cadena aplicada a cada respuesta antes del Dashboard:
  RecursionGuard → ToneGuard → LogicIntegrityFilter

Cada filtro está decorado con @measure_latency, que unifica:
  - ExecutionTimeout watchdog (asyncio.wait_for, 5 s)
  - Telemetría JSON: filtro, duracion_s, status
"""

import asyncio
import functools
import logging
import re
import time
from collections import deque
from typing import Callable, ClassVar

logger = logging.getLogger(__name__)

TIMEOUT_FILTRO: float = 30.0   # Groq puede tardar más con archivos grandes
_UMBRAL_BUCLE: int = 3
_MAX_HISTORIAL: int = 10


# ── Excepciones propias ────────────────────────────────────────────────────────

class RecursionLoopError(RuntimeError):
    pass

class ToneError(ValueError):
    pass

class GroundingError(ValueError):
    """El agente citó información no presente en los datos de entrada (alucinación)."""
    pass


# ── Helpers ────────────────────────────────────────────────────────────────────

_PALABRAS_COLOQUIALES: frozenset[str] = frozenset({
    "wow", "cool", "genial", "alucinante", "increible", "buenisimo",
    "malisimo", "super", "fatal", "horrible", "bro", "tio", "dale",
    "lol", "xd", "omg", "jajaja", "jeje", "brutal", "flojo", "pesimo",
    "basicamente", "obvio", "oye", "mira", "vamos",
})


def _extraer_numeros(texto: str) -> list[float]:
    """Extrae valores numéricos ignorando símbolos monetarios y porcentajes."""
    limpio = re.sub(r"[$,%]", "", str(texto))
    return [float(m) for m in re.findall(r"\d+(?:\.\d+)?", limpio) if float(m) > 0]


def _valores_planos(obj: dict | list | str, acum: list | None = None) -> list[str]:
    """Aplana recursivamente un dict/list hasta obtener una lista de strings."""
    if acum is None:
        acum = []
    if isinstance(obj, dict):
        for v in obj.values():
            _valores_planos(v, acum)
    elif isinstance(obj, list):
        for item in obj:
            _valores_planos(item, acum)
    else:
        acum.append(str(obj))
    return acum


# ── Decorador @measure_latency ─────────────────────────────────────────────────

def measure_latency(fn):
    """
    Decora un filtro async con:
      1. ExecutionTimeout: asyncio.wait_for de TIMEOUT_FILTRO segundos.
      2. Telemetría: registro JSON con filtro, agente, duracion_s y status.

    Cuando decora un método de PipelineProcessor, extrae nombre_agente de
    args[0] para incluirlo en cada entrada de log — imprescindible para
    distinguir agentes en la ejecución paralela.
    """
    nombre = fn.__name__.lstrip("_").replace("_", " ").title()

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        agente = getattr(args[0], "nombre_agente", None) if args else None
        extra_base: dict = {"filtro": nombre}
        if agente:
            extra_base["agente"] = agente

        inicio = time.monotonic()
        try:
            resultado = await asyncio.wait_for(
                fn(*args, **kwargs), timeout=TIMEOUT_FILTRO
            )
            duracion = round(time.monotonic() - inicio, 4)
            logger.info(
                "Filtro ejecutado",
                extra={**extra_base, "duracion_s": duracion, "status": "ok"},
            )
            return resultado

        except asyncio.TimeoutError:
            duracion = round(time.monotonic() - inicio, 4)
            logger.error(
                "Filtro timeout — watchdog activado",
                extra={**extra_base, "duracion_s": duracion, "status": "timeout"},
            )
            raise

        except Exception as exc:
            duracion = round(time.monotonic() - inicio, 4)
            logger.error(
                "Filtro fallido",
                extra={**extra_base, "duracion_s": duracion, "status": "error",
                       "detalle": str(exc)},
            )
            raise

    return wrapper


# ── PipelineProcessor ──────────────────────────────────────────────────────────

class PipelineProcessor:
    """
    Orquesta la cadena de guardrails para un agente específico.
    Instanciar una vez por agente para que RecursionGuard mantenga
    su historial propio.
    """

    # Hook de clase: se cablea desde main.py para desacoplar core/ de ui/
    # Firma: (filtro: str, exc: Exception, reporte: dict, raw_data: dict) -> None
    _abort_hook: ClassVar[Callable | None] = None

    def __init__(self, nombre_agente: str) -> None:
        self.nombre_agente = nombre_agente
        self._historial: deque[str] = deque(maxlen=_MAX_HISTORIAL)
        # Veredicto de CADA guardrail evaluado en la ultima corrida
        # (ADR-0014): registro forense completo, no solo el que aborta.
        self.ultimo_veredicto: list[dict] = []

    # ── Punto de entrada ───────────────────────────────────────────────────────

    async def procesar(
        self,
        raw_data: dict,
        respuesta_texto: str,
        reporte: dict,
    ) -> dict | None:
        """
        Ejecuta los guardrails en orden. Retorna el reporte (posiblemente
        anotado) o None si algún filtro aborta la cadena.
        """
        resultado = await self.procesar_con_razon(raw_data, respuesta_texto, reporte)
        if resultado is None or resultado.get("_abortado"):
            return None
        return resultado

    async def procesar_con_razon(
        self,
        raw_data: dict,
        respuesta_texto: str,
        reporte: dict,
    ) -> dict | None:
        """
        Como procesar() pero devuelve {"_abortado": True, "_guardrail": "...", "_razon": "..."}
        cuando un guardrail rechaza, en lugar de None.
        Esto permite al orquestador corregir el error automáticamente.
        """
        from core.telemetry_otel import medir_paso
        veredictos: list[dict] = []

        # 1. RecursionGuard
        try:
            with medir_paso("guardrail.RecursionGuard", agente=self.nombre_agente):
                await self._recursion_guard(respuesta_texto)
        except (RecursionLoopError, asyncio.TimeoutError) as exc:
            self._log_abort("RecursionGuard", exc, reporte, raw_data)
            veredictos.append({"guardrail": "RecursionGuard", "veredicto": "rechazado", "razon": str(exc)})
            self.ultimo_veredicto = veredictos
            return {"_abortado": True, "_guardrail": "RecursionGuard",
                    "_razon": f"Respuesta repetida detectada ({exc}). Genera una respuesta diferente con nueva perspectiva."}
        veredictos.append({"guardrail": "RecursionGuard", "veredicto": "aprobado"})

        # 2. ToneGuard
        try:
            with medir_paso("guardrail.ToneGuard", agente=self.nombre_agente):
                await self._tone_guard(reporte)
        except (ToneError, asyncio.TimeoutError) as exc:
            self._log_abort("ToneGuard", exc, reporte, raw_data)
            veredictos.append({"guardrail": "ToneGuard", "veredicto": "rechazado", "razon": str(exc)})
            self.ultimo_veredicto = veredictos
            return {"_abortado": True, "_guardrail": "ToneGuard",
                    "_razon": f"Tono inapropiado: {exc}. Usa lenguaje profesional, técnico y objetivo sin coloquialismos."}
        veredictos.append({"guardrail": "ToneGuard", "veredicto": "aprobado"})

        # 3. GroundingGuard
        try:
            with medir_paso("guardrail.GroundingGuard", agente=self.nombre_agente):
                await self._grounding_guard(raw_data, reporte)
        except (GroundingError, asyncio.TimeoutError) as exc:
            self._log_abort("GroundingGuard", exc, reporte, raw_data)
            veredictos.append({"guardrail": "GroundingGuard", "veredicto": "rechazado", "razon": str(exc)})
            self.ultimo_veredicto = veredictos
            return {"_abortado": True, "_guardrail": "GroundingGuard",
                    "_razon": (f"Valores en 'evidencia' no encontrados en los datos originales: {exc}. "
                               "Cita los valores EXACTAMENTE como aparecen en los datos, sin redondear ni formatear diferente.")}
        veredictos.append({"guardrail": "GroundingGuard", "veredicto": "aprobado"})

        # 4. LogicIntegrityFilter
        try:
            with medir_paso("guardrail.LogicIntegrityFilter", agente=self.nombre_agente):
                reporte = await self._logic_integrity_filter(raw_data, reporte)
        except asyncio.TimeoutError as exc:
            self._log_abort("LogicIntegrityFilter", exc, reporte, raw_data)
            veredictos.append({"guardrail": "LogicIntegrityFilter", "veredicto": "rechazado", "razon": str(exc)})
            self.ultimo_veredicto = veredictos
            return {"_abortado": True, "_guardrail": "LogicIntegrity",
                    "_razon": f"Timeout en verificación de integridad: {exc}."}
        veredictos.append({"guardrail": "LogicIntegrityFilter", "veredicto": "aprobado"})

        self.ultimo_veredicto = veredictos
        return reporte

    # ── Filtros ────────────────────────────────────────────────────────────────

    @measure_latency
    async def _recursion_guard(self, respuesta_texto: str) -> None:
        """
        Registra la respuesta en el historial del agente.
        Si las últimas _UMBRAL_BUCLE respuestas son idénticas, aborta.
        """
        self._historial.append(respuesta_texto)
        if len(self._historial) >= _UMBRAL_BUCLE:
            ultimas = list(self._historial)[-_UMBRAL_BUCLE:]
            if len(set(ultimas)) == 1:
                raise RecursionLoopError(
                    f"Bucle detectado: respuesta idéntica en los últimos "
                    f"{_UMBRAL_BUCLE} registros del agente '{self.nombre_agente}'."
                )

    @measure_latency
    async def _tone_guard(self, reporte: dict) -> None:
        """
        Rechaza respuestas con lenguaje coloquial o no profesional.
        Aplica sobre resumen y celdas de la tabla.
        """
        texto = " ".join(_valores_planos(reporte)).lower()
        palabras = set(re.findall(r"\b[a-záéíóúüñ]+\b", texto))
        encontradas = _PALABRAS_COLOQUIALES & palabras
        if encontradas:
            raise ToneError(
                f"Tono no profesional: {sorted(encontradas)}"
            )

    @measure_latency
    async def _grounding_guard(self, raw_data: dict, reporte: dict) -> None:
        """
        Verifica que cada KPI citado en 'evidencia' pueda rastrearse
        hasta los datos de entrada (raw_data). Aborta si detecta
        valores fabricados no presentes en el contexto original.

        Estrategia:
          1. Construir un corpus de texto con todos los valores de raw_data.
          2. Para cada entrada de 'evidencia', extraer sus valores numéricos.
          3. Si un número citado no aparece en el corpus, es una alucinación.
        """
        import json as _json

        evidencia = reporte.get("evidencia", {})
        es_externo = raw_data.get("_es_texto_externo", False)

        # Para datos externos (CSV/texto subido) la evidencia es opcional
        if not evidencia and not es_externo:
            raise GroundingError(
                "El reporte no incluye campo 'evidencia'. "
                "El agente debe citar la fuente de cada KPI."
            )
        if not evidencia:
            return  # datos externos sin evidencia → OK

        # Corpus: para datos externos usar _corpus directamente
        corpus_raw = raw_data.get("_corpus", "") if es_externo else _json.dumps(raw_data, ensure_ascii=False)
        corpus = re.sub(r"[$,%\s]", "", corpus_raw.lower())

        alucinaciones: list[str] = []

        for kpi, fuente in evidencia.items():
            numeros_citados = _extraer_numeros(fuente)
            for num in numeros_citados:
                # Solo verificar valores numéricos significativos (≥ 1 000)
                # para evitar falsos positivos con porcentajes, multiplicadores
                # y pequeños índices que aparecen en fórmulas de evidencia.
                if num < 1_000:
                    continue
                num_normalizado = re.sub(r"[.,]", "", str(int(num)))
                if num_normalizado not in corpus:
                    alucinaciones.append(
                        f"KPI '{kpi}' cita {num:g} — no encontrado en los datos originales"
                    )

        if alucinaciones:
            muestra = "; ".join(alucinaciones[:3])
            sufijo  = f" (+{len(alucinaciones)-3} más)" if len(alucinaciones) > 3 else ""
            raise GroundingError(
                f"Alucinacion detectada en {len(alucinaciones)} KPI(s): {muestra}{sufijo}."
            )

    @measure_latency
    async def _logic_integrity_filter(self, raw_data: dict, reporte: dict) -> dict:
        """
        Compara los valores numéricos significativos de los KPIs contra
        los datos crudos. Si un KPI excede 100× el máximo de los datos
        de origen, anota 'Error de Integridad' en el reporte.
        """
        numeros_crudos = [
            n for v in _valores_planos(raw_data)
            for n in _extraer_numeros(v)
            if n > 1_000
        ]
        numeros_kpi = [
            n for v in _valores_planos(reporte.get("kpis", {}))
            for n in _extraer_numeros(v)
            if n > 1_000
        ]

        if not numeros_crudos or not numeros_kpi:
            return reporte

        max_crudo = max(numeros_crudos)
        for kpi_num in numeros_kpi:
            if kpi_num > max_crudo * 100:
                reporte = dict(reporte)
                reporte["_integridad"] = (
                    f"Error de Integridad: KPI {kpi_num:,.0f} excede "
                    f"100× el máximo de los datos crudos ({max_crudo:,.0f})."
                )
                logger.warning(
                    "Integridad cuestionable en reporte",
                    extra={
                        "agente": self.nombre_agente,
                        "kpi_num": kpi_num,
                        "raw_max": max_crudo,
                        "ratio": round(kpi_num / max_crudo, 1),
                    },
                )
                break

        return reporte

    # ── Helpers privados ───────────────────────────────────────────────────────

    def _log_abort(
        self,
        filtro: str,
        exc: Exception,
        reporte: dict | None = None,
        raw_data: dict | None = None,
    ) -> None:
        logger.error(
            "Pipeline abortado",
            extra={
                "agente": self.nombre_agente,
                "filtro": filtro,
                "motivo": str(exc),
                "status": "abortado",
            },
        )
        if PipelineProcessor._abort_hook is not None:
            try:
                PipelineProcessor._abort_hook(
                    self.nombre_agente, filtro, exc, reporte or {}, raw_data or {}
                )
            except Exception as hook_exc:
                logger.warning("CorrectionAgent hook fallido: %s", hook_exc)
