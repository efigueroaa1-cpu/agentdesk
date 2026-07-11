"""
Stress test: 20 agentes Dummy concurrentes via asyncio.gather().

Objetivo: verificar que el PipelineProcessor y el sistema de logging
soportan alta concurrencia sin colisiones de estado ni degradacion.

Ejecutar con:  python stress_test.py
"""

import asyncio
import logging
import random
import time

from core.log_config import configurar_logging
from core.orchestrator import AgentBase, Orquestador   # noqa: F401 — importado como referencia
from core.pipeline import PipelineProcessor

configurar_logging()
log = logging.getLogger(__name__)

NUM_AGENTES: int = 20

_RAW_DUMMY: dict = {
    "reporte_ventas": {"Q1": "$50,000", "Q2": "$62,000", "Q3": "$75,000"},
}


# ── Agente Dummy ───────────────────────────────────────────────────────────────

class DummyAgent(AgentBase):
    """
    Subclase de AgentBase que sustituye la llamada real a la API de Gemini
    por un sleep aleatorio, permitiendo estresar el pipeline sin cuota.

    Flujo real conservado:
      asyncio.sleep (simula LLM) → reporte dict → PipelineProcessor completo
    """

    def __init__(self, agent_id: int) -> None:
        super().__init__(
            config={"nombre": f"Dummy-{agent_id:02d}", "tipo_ia": "dummy"},
            client=None,            # no se usa: realizar_tarea está redefinido
            model_name_global="dummy-v1",
        )
        self.agent_id = agent_id

    async def realizar_tarea(self, tarea: str = "stress_test") -> dict | None:  # type: ignore[override]
        latencia = random.uniform(1.0, 3.0)
        await asyncio.sleep(latencia)                   # simula latencia de LLM

        reporte = {
            "resumen": (
                f"Agente {self.nombre}: análisis de carga completado. "
                f"Latencia simulada: {latencia:.2f}s."
            ),
            "kpis": {
                "Latencia_s":  f"{latencia:.2f}",
                "Agente_ID":   str(self.agent_id),
                "Estado":      "Completado",
            },
            "tabla": [
                ["Agente",      "Latencia (s)", "Estado"],
                [self.nombre,   f"{latencia:.2f}", "OK"],
            ],
            # GroundingGuard requiere evidencia; sin valores > 1 000 no hay alucinaciones
            "evidencia": {
                "Estado": "Ejecución de pipeline sobre datos de reporte_ventas (stress test)",
            },
        }
        # Texto único (agente + timestamp) — RecursionGuard nunca dispara
        texto = f"agente={self.agent_id} ts={time.monotonic():.9f}"
        return await self.pipeline.procesar(_RAW_DUMMY, texto, reporte)


# ── Runner ─────────────────────────────────────────────────────────────────────

async def run_stress_test(num_agentes: int = NUM_AGENTES) -> None:
    agentes = [DummyAgent(i + 1) for i in range(num_agentes)]

    sep     = "=" * 64
    sep_mid = "-" * 64

    print(f"\n{sep}")
    print(f"  STRESS TEST  —  {num_agentes} agentes concurrentes")
    print(sep)
    print(f"  Carga simulada : asyncio.sleep  U[1.0s, 3.0s] por agente")
    print(f"  Tiempo max seq : ~{num_agentes * 3:.0f}s  |  Esperado paralelo: ~3s")
    print(f"  Pipeline       : PipelineProcessor completo (guardrails reales)")
    print(f"{sep_mid}")
    print(f"  Lanzando {num_agentes} tareas con asyncio.gather() ...\n")

    inicio     = time.monotonic()
    resultados = await asyncio.gather(
        *[a.realizar_tarea() for a in agentes],
        return_exceptions=True,
    )
    duracion = time.monotonic() - inicio

    # ── Conteo de resultados ───────────────────────────────────────────────────
    exitosos   = sum(1 for r in resultados if isinstance(r, dict))
    rechazados = sum(1 for r in resultados if r is None)
    errores    = sum(1 for r in resultados if isinstance(r, BaseException))

    tiempo_seq_worst = num_agentes * 3.0        # worst-case secuencial
    factor           = tiempo_seq_worst / duracion
    tasa_exito       = exitosos / num_agentes * 100

    print(f"{sep}")
    print(f"  RESULTADOS")
    print(sep)
    print(f"  Agentes lanzados      : {num_agentes}")
    print(f"  Completados   [OK]    : {exitosos}")
    print(f"  Rechazados  [None]    : {rechazados}  (guardrails activos)")
    print(f"  Excepciones  [ERR]    : {errores}")
    print(f"{sep_mid}")
    print(f"  Tiempo real           : {duracion:.2f}s")
    print(f"  Tiempo seq. estimado  : ~{tiempo_seq_worst:.0f}s  (worst-case secuencial)")
    print(f"  Factor de aceleracion : {factor:.1f}x mas rapido")
    print(f"  Tasa de exito         : {exitosos}/{num_agentes}  ({tasa_exito:.1f}%)")
    print(sep)

    log.info(
        "Stress test completado",
        extra={
            "num_agentes":     num_agentes,
            "exitosos":        exitosos,
            "rechazados":      rechazados,
            "errores":         errores,
            "duracion_s":      round(duracion, 3),
            "factor_paralelo": round(factor, 1),
            "tasa_exito_pct":  round(tasa_exito, 1),
        },
    )

    # ── Veredicto ──────────────────────────────────────────────────────────────
    if exitosos == num_agentes:
        print(f"\n  [PASS] {num_agentes}/{num_agentes} agentes completaron el pipeline.")
    else:
        print(
            f"\n  [WARN] {exitosos}/{num_agentes} completaron. "
            "Revisa logs/sistema.log para el detalle."
        )


if __name__ == "__main__":
    asyncio.run(run_stress_test())
