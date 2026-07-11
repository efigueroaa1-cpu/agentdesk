"""
CorrectionAgent: análisis de errores de guardrails y generación de
sugerencias de corrección accionables.

Se activa automáticamente cuando PipelineProcessor._abort_hook está
configurado (lo hace main.py). No depende de la UI ni de la API externa.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal


# ── Estructura de salida ───────────────────────────────────────────────────────

@dataclass
class Sugerencia:
    filtro:      str
    causa_raiz:  str
    accion:      str
    ejemplo:     str | None = None
    log_excerpt: dict | None = None
    severidad:   Literal["INFO", "WARNING", "CRITICAL"] = "WARNING"


# ── Agente correctivo ──────────────────────────────────────────────────────────

class CorrectionAgent:
    """
    Analiza el contexto de un fallo de guardrail y devuelve una Sugerencia
    con causa raíz, acción recomendada, ejemplo y extracto del log JSON.
    """

    def analizar(
        self,
        filtro:   str,
        motivo:   str,
        reporte:  dict,
        raw_data: dict,
    ) -> Sugerencia:
        log_entry = self._leer_ultima_entrada_log(filtro)

        filtro_lower = filtro.lower().replace(" ", "")
        motivo_lower = motivo.lower()

        if "timeout" in motivo_lower:
            sug = self._timeout(filtro)
        elif "recursion" in filtro_lower:
            sug = self._recursion(motivo)
        elif "tone" in filtro_lower:
            sug = self._tono(motivo, reporte)
        elif "integrity" in filtro_lower or "logic" in filtro_lower:
            sug = self._integridad(motivo, reporte, raw_data)
        elif "grounding" in filtro_lower:
            sug = self._grounding(motivo, reporte, raw_data)
        else:
            sug = self._generico(filtro, motivo)

        sug.log_excerpt = log_entry
        return sug

    # ── Analizadores por guardrail ─────────────────────────────────────────────

    def _timeout(self, filtro: str) -> Sugerencia:
        return Sugerencia(
            filtro=filtro,
            severidad="CRITICAL",
            causa_raiz=(
                f"El filtro '{filtro}' superó el límite de 5 s (TIMEOUT_FILTRO). "
                "La carga de datos o la complejidad del texto de entrada es excesiva."
            ),
            accion=(
                "Opcion A — Aumenta TIMEOUT_FILTRO en core/pipeline.py (actual: 5.0 s).\n"
                "Opcion B — Reduce el volumen de datos en datos_trabajo.json.\n"
                "Opcion C — Limita el numero de campos en 'kpis' para aligerar\n"
                "           el analisis del LogicIntegrityFilter."
            ),
            ejemplo="TIMEOUT_FILTRO: float = 10.0   # en core/pipeline.py, linea 21",
        )

    def _recursion(self, motivo: str) -> Sugerencia:
        return Sugerencia(
            filtro="RecursionGuard",
            severidad="CRITICAL",
            causa_raiz=(
                "El agente generó respuestas identicas en 3 llamadas consecutivas. "
                "Causa tipica: datos estaticos que producen un prompt identico cada vez, "
                "o el modelo esta devolviendo una respuesta en cache."
            ),
            accion=(
                "1. Verifica que datos_trabajo.json se actualice entre ejecuciones.\n"
                "2. Añade variacion al prompt (timestamp, run_id o semilla aleatoria).\n"
                "3. Revisa parametros del modelo: incrementa temperature o top_p."
            ),
            ejemplo=(
                "# En core/orchestrator.py — AgentBase.realizar_tarea():\n"
                "import time\n"
                'instruccion = f"[Run {time.time():.0f}] Analiza: {datos} ..."'
            ),
        )

    def _tono(self, motivo: str, reporte: dict) -> Sugerencia:
        match = re.search(r"\[(.+?)\]", motivo)
        palabras = match.group(1) if match else "palabras coloquiales"

        return Sugerencia(
            filtro="ToneGuard",
            severidad="WARNING",
            causa_raiz=(
                f"La respuesta contiene lenguaje no profesional: {palabras}. "
                "El modelo ignoro o interpreto de forma laxa la instruccion de tono."
            ),
            accion=(
                "Refuerza la instruccion de tono al final del prompt en\n"
                "core/orchestrator.py — AgentBase.realizar_tarea():\n"
                '  "Usa un tono estrictamente profesional y corporativo.\n'
                '   Evita expresiones informales, coloquiales o exclamaciones."'
            ),
            ejemplo=(
                f"Palabras detectadas: {palabras}\n"
                "Sustituciones sugeridas:\n"
                '  "wow / super / genial"  ->  "notable / significativo / destacado"\n'
                '  "bro / tio / dale"      ->  eliminar o usar "el equipo / el sistema"'
            ),
        )

    def _integridad(
        self, motivo: str, reporte: dict, raw_data: dict
    ) -> Sugerencia:
        nums = re.findall(r"\d[\d,.]*", motivo)
        kpi_val = nums[0] if len(nums) > 0 else "desconocido"
        raw_max = nums[1] if len(nums) > 1 else "desconocido"

        return Sugerencia(
            filtro="LogicIntegrityFilter",
            severidad="WARNING",
            causa_raiz=(
                f"Un KPI reportado ({kpi_val}) supera 100x el valor maximo "
                f"encontrado en los datos crudos ({raw_max}). "
                "El modelo puede haber confundido unidades (miles vs. millones) "
                "o generado un valor alucinado."
            ),
            accion=(
                "1. Revisa la escala de datos_trabajo.json\n"
                "   (verifica si los valores estan en unidades, miles o millones).\n"
                "2. Añade al prompt una restriccion de escala:\n"
                '   "Los KPIs deben expresarse en la misma escala que\n'
                '    los datos de entrada. No extrapoles ni cambies de unidad."\n'
                "3. Si el valor es correcto, amplia el umbral en core/pipeline.py:"
            ),
            ejemplo=(
                f"# Dato crudo max: {raw_max}   KPI recibido: {kpi_val}\n"
                "# En core/pipeline.py — _logic_integrity_filter, linea ~221:\n"
                "  if kpi_num > max_crudo * 500:   # umbral ampliado"
            ),
        )

    def _grounding(self, motivo: str, reporte: dict, raw_data: dict) -> Sugerencia:
        """
        El agente citó valores en 'evidencia' que no existen en raw_data.
        Usa raw_data para mostrar qué campos SÍ están disponibles,
        y reporte para identificar qué KPIs fueron los problemáticos.
        """
        # KPIs que fallaron según el mensaje de error
        kpis_problematicos = re.findall(r"KPI '([^']+)'", motivo)
        lista_kpis = ", ".join(f"'{k}'" for k in kpis_problematicos[:4]) or "varios KPIs"

        # Campos raíz disponibles en raw_data → guía concreta para el agente
        campos_disponibles = list(raw_data.keys()) if isinstance(raw_data, dict) else []
        campos_str = ", ".join(f"'{c}'" for c in campos_disponibles[:6])

        # KPIs que generó el agente → mostrar cuáles debería revisar
        kpis_generados = list(reporte.get("kpis", {}).keys())[:4]
        kpis_str = ", ".join(f"'{k}'" for k in kpis_generados) or "los KPIs del reporte"

        return Sugerencia(
            filtro="GroundingGuard",
            severidad="CRITICAL",
            causa_raiz=(
                f"El agente generó valores en 'evidencia' para {lista_kpis} "
                "que no pueden rastrearse en los datos de entrada. "
                "El modelo fabricó cifras en lugar de citar el contexto real (alucinacion).\n"
                f"  KPIs generados: {kpis_str}.\n"
                f"  Campos disponibles en raw_data: {campos_str}."
            ),
            accion=(
                "Añade al prompt_base del agente en config.json:\n"
                '  "RESTRICCION CRITICA: Solo puedes referenciar valores que\n'
                '   aparezcan LITERALMENTE en los datos proporcionados.\n'
                '   En el campo evidencia copia el valor exacto de la fuente\n'
                '   (ej. reporte_ventas.Mayo = $75,000).\n'
                '   Para calculos, muestra la operacion con valores originales\n'
                '   (ej. (75000-50000)/50000 = 50%). Nunca inventes cifras."'
            ),
            ejemplo=(
                f"# Campos raiz disponibles en raw_data: {campos_str}\n"
                "# Estructura correcta del campo 'evidencia':\n"
                "{\n"
                '  "Ventas_Mayo":  "reporte_ventas.Mayo = $75,000",\n'
                '  "Crecimiento":  "calculado: (75000-50000)/50000 = 50%",\n'
                '  "Estado":       "estado_sistema.Estado = Operativo"\n'
                "}"
            ),
        )

    def _generico(self, filtro: str, motivo: str) -> Sugerencia:
        return Sugerencia(
            filtro=filtro,
            severidad="WARNING",
            causa_raiz=f"Error no clasificado en '{filtro}': {motivo[:140]}",
            accion=(
                "Consulta logs/sistema.log para el stack trace completo.\n"
                "Verifica que el formato del reporte coincide con\n"
                "ReporteAgente definido en core/schemas.py."
            ),
        )

    # ── Lector de log JSON ─────────────────────────────────────────────────────

    def _leer_ultima_entrada_log(self, filtro: str) -> dict | None:
        """
        Busca la entrada de error mas reciente en logs/sistema.log
        que corresponda al filtro que acaba de fallar.
        """
        filtro_norm = filtro.lower().replace(" ", "").replace("_", "")
        try:
            with open("logs/sistema.log", encoding="utf-8") as f:
                lineas = [l.strip() for l in f if l.strip().startswith("{")]

            for linea in reversed(lineas[-200:]):
                try:
                    entry = json.loads(linea)
                    entry_filtro = (
                        entry.get("filtro", "").lower().replace(" ", "")
                    )
                    nivel = entry.get("level", "").upper()
                    if (filtro_norm in entry_filtro or entry_filtro in filtro_norm) \
                            and nivel in ("ERROR", "WARNING"):
                        return entry
                except json.JSONDecodeError:
                    continue
        except (OSError, IOError):
            pass
        return None
