# -*- coding: utf-8 -*-
"""
tests/stress/test_db_concurrency.py — Concurrencia de escritura en la base
de datos (Fase 18, ADR-0016).

Simula NUM_AGENTES agentes de planta escribiendo simultáneamente en la
tabla auditoria_ia (el mismo camino de escritura que usa cada interacción
real: audit_service.registrar_interaccion() -> core.database.get_session()).
Mide el tiempo de cada escritura individual (proxy de espera de lock) y
valida que el pool de conexiones (ADR-0005/0013: pool_pre_ping/pool_size=10/
max_overflow=20 en PostgreSQL, StaticPool + WAL en SQLite) absorbe la
concurrencia sin escrituras perdidas ni bloqueos patológicos.

**Limitación honesta (mismo patrón que Fase 13/15):** no hay un servidor
PostgreSQL real disponible en este entorno de desarrollo — este archivo
ejercita el camino REAL contra SQLite (motor por defecto, ADR-0005), que
es el único servidor de base de datos que existe en la máquina de
desarrollo. El código bajo prueba (audit_service.registrar_interaccion /
get_session) es agnóstico al motor: si AGENTDESK_DB_URL apunta a un
PostgreSQL real, este mismo test ejercitaría ese pool sin cambios. No se
fabrica ninguna demostración de PostgreSQL que no se pueda correr en vivo.

Usa una base SQLite temporal — no toca la DB real del usuario.
"""
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import core.database as db
from core.services import audit_service

NUM_AGENTES = 10
ESCRITURAS_POR_AGENTE = 5
TOTAL_ESPERADO = NUM_AGENTES * ESCRITURAS_POR_AGENTE

# Umbral generoso (no busca medir rendimiento absoluto, sino detectar un
# bloqueo patológico real: un deadlock o una cola de lock que no drena).
MAX_SEGUNDOS_POR_ESCRITURA = 5.0
MAX_SEGUNDOS_TOTAL         = 30.0


def _escribir_una(agente_idx: int, intento_idx: int) -> tuple[int | None, float]:
    """Una escritura real vía el mismo camino que usa cada interacción de agente."""
    inicio = time.monotonic()
    _id = audit_service.registrar_interaccion(
        tipo="chat",
        agente_id=f"agente.planta.{agente_idx:02d}",
        prompt=f"lectura de sensor #{intento_idx}",
        respuesta="ok",
        user_id=f"op.turno.{agente_idx % 3}",
    )
    duracion = time.monotonic() - inicio
    return _id, duracion


class TestConcurrenciaEscrituraDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = Path(tempfile.mkdtemp()) / "stress_concurrency_test.db"
        db.init_db(db_path=cls.db_path)

    def test_01_diez_agentes_escriben_simultaneamente_sin_perder_datos(self):
        """
        NUM_AGENTES hilos, cada uno con su propia sesión (get_session() por
        llamada, mismo patrón que producción), escribiendo al mismo tiempo.
        Ninguna escritura debe perderse ni quedar en None (best-effort de
        audit_service solo devuelve None si la escritura realmente falló).
        """
        tareas = [
            (agente_idx, intento_idx)
            for agente_idx in range(NUM_AGENTES)
            for intento_idx in range(ESCRITURAS_POR_AGENTE)
        ]

        inicio_total = time.monotonic()
        resultados: list[tuple[int | None, float]] = []
        with ThreadPoolExecutor(max_workers=NUM_AGENTES) as pool:
            futuros = [pool.submit(_escribir_una, a, i) for a, i in tareas]
            for f in as_completed(futuros):
                resultados.append(f.result())
        duracion_total = time.monotonic() - inicio_total

        ids       = [r[0] for r in resultados]
        duraciones = [r[1] for r in resultados]

        # 1. Ninguna escritura se perdió (best-effort -> None solo si fallo real)
        fallidas = [i for i, _id in enumerate(ids) if _id is None]
        self.assertEqual(
            fallidas, [],
            f"{len(fallidas)}/{TOTAL_ESPERADO} escrituras concurrentes fallaron "
            f"(deberian ser 0 con el pool de conexiones absorbiendo la carga)",
        )

        # 2. IDs únicos: cada escritura generó su propia fila (sin pisarse)
        self.assertEqual(
            len(set(ids)), TOTAL_ESPERADO,
            "Hay IDs de auditoria repetidos o faltantes -- posible condicion "
            "de carrera en el pool de conexiones",
        )

        # 3. Ninguna escritura individual quedó bloqueada de forma patológica
        peor = max(duraciones)
        self.assertLess(
            peor, MAX_SEGUNDOS_POR_ESCRITURA,
            f"La escritura mas lenta tardo {peor:.2f}s (>{MAX_SEGUNDOS_POR_ESCRITURA}s) "
            f"-- posible lock no liberado / contencion severa del pool",
        )

        # 4. El total no se comportó como una cola infinita
        self.assertLess(
            duracion_total, MAX_SEGUNDOS_TOTAL,
            f"{TOTAL_ESPERADO} escrituras concurrentes tardaron {duracion_total:.2f}s "
            f"en total (>{MAX_SEGUNDOS_TOTAL}s)",
        )

        print(
            f"\n  [STRESS] {TOTAL_ESPERADO} escrituras / {NUM_AGENTES} agentes: "
            f"total={duracion_total:.3f}s  promedio={sum(duraciones)/len(duraciones):.3f}s  "
            f"peor={peor:.3f}s"
        )

    def test_02_todas_las_filas_quedan_persistidas_y_consultables(self):
        """Verificación independiente contra la DB: 50 filas nuevas, una por agente/intento."""
        for agente_idx in range(NUM_AGENTES):
            for intento_idx in range(ESCRITURAS_POR_AGENTE):
                _id, _ = _escribir_una(agente_idx, intento_idx)
                self.assertIsNotNone(_id)

        total_filas = 0
        for agente_idx in range(NUM_AGENTES):
            filas = audit_service.consultar(
                agente_id=f"agente.planta.{agente_idx:02d}", limit=500,
            )
            total_filas += len(filas)
        self.assertGreaterEqual(total_filas, TOTAL_ESPERADO)


if __name__ == "__main__":
    unittest.main()
