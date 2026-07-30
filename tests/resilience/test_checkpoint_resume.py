# -*- coding: utf-8 -*-
"""
tests/resilience/test_checkpoint_resume.py — Reanudacion de corrida (Soberania
de Datos, 2026-07-30).

Garantia: si una corrida batch (ejecutar_todos_paralelo) se interrumpe, al
relanzarla con el mismo corrida_id los agentes ya completados se leen del
checkpoint persistido en SQLite y NO se re-ejecutan; solo corren los pendientes.

Criterio:
  - Corrida 1: agente A entrega reporte valido, agente B falla (None). Se
    persiste checkpoint de A; B no deja checkpoint.
  - Corrida 2 (mismo corrida_id): A NO se re-ejecuta (viene del checkpoint),
    B si; el resultado final tiene ambos agentes.
  - La escritura de checkpoint es atomica e idempotente: reescribir el mismo
    (corrida_id, agente_id) actualiza la fila, no la duplica.

Usa una DB SQLite temporal — no toca la del usuario.
"""
import tempfile
import unittest
from pathlib import Path

import core.database as db
from core.orchestrator.engine import OrquestadorEngineMixin
from core.repositories.checkpoint_repository import (
    guardar_checkpoint, obtener_checkpoints, limpiar_checkpoints,
)

_VALIDO = {"resumen": "ok", "kpis": {"Temp": "96.0"},
           "tabla": [["Variable", "Valor"], ["temperatura", "96.0"]],
           "evidencia": {"Temp": "telemetria.U1.temperatura=96.0"}}


class _FakeAgente:
    """Agente minimo: cuenta cuantas veces se le pide realizar_tarea."""

    def __init__(self, nombre, resultado, contador):
        self.nombre = nombre
        self.modelo = "ollama:llama3.2"
        self.ultimo_proveedor_llm = "ollama"
        self.ultimo_tokens_llm = None
        self._resultado = resultado
        self._contador = contador

    async def realizar_tarea(self, tarea, _datos_override=None):
        self._contador[self.nombre] = self._contador.get(self.nombre, 0) + 1
        return self._resultado


class _Orq(OrquestadorEngineMixin):
    def __init__(self, agentes):
        self.config = {"orquestador": {"max_agentes_paralelo": 2,
                                       "timeout_tarea_s": 5}}
        self.agentes = agentes


class TestCheckpointResume(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "checkpoint_test.db")

    async def test_01_reanuda_agentes_completados(self):
        corrida = "test-corrida-resume"
        limpiar_checkpoints(corrida)

        # Corrida 1: A entrega valido, B falla (None -> sin checkpoint).
        cont1: dict = {}
        orq1 = _Orq({
            "a": _FakeAgente("A", dict(_VALIDO), cont1),
            "b": _FakeAgente("B", None, cont1),
        })
        r1 = await orq1.ejecutar_todos_paralelo(
            "reporte_ventas", max_paralelo=2, corrida_id=corrida)
        self.assertIsNotNone(r1[0])
        self.assertIsNone(r1[1])

        ck = obtener_checkpoints(corrida)
        self.assertIn("a", ck, "A completado debe quedar en checkpoint")
        self.assertNotIn("b", ck, "B fallido NO debe dejar checkpoint")

        # Corrida 2 (mismo id): A no se re-ejecuta; B si.
        cont2: dict = {}
        orq2 = _Orq({
            "a": _FakeAgente("A", dict(_VALIDO), cont2),
            "b": _FakeAgente("B", dict(_VALIDO), cont2),
        })
        r2 = await orq2.ejecutar_todos_paralelo(
            "reporte_ventas", max_paralelo=2, corrida_id=corrida)

        self.assertEqual(cont2.get("A", 0), 0,
                         "A ya completado no debe re-ejecutarse (viene del checkpoint)")
        self.assertEqual(cont2.get("B", 0), 1,
                         "B pendiente debe ejecutarse en la reanudacion")
        self.assertIsNotNone(r2[0])
        self.assertIsNotNone(r2[1])
        limpiar_checkpoints(corrida)

    def test_02_escritura_atomica_idempotente(self):
        corrida = "test-corrida-atomica"
        limpiar_checkpoints(corrida)

        guardar_checkpoint(corrida, "x", {"resumen": "v1", "kpis": {"a": "1"}})
        guardar_checkpoint(corrida, "x", {"resumen": "v2", "kpis": {"a": "2"}})

        ck = obtener_checkpoints(corrida)
        self.assertEqual(len(ck), 1, "reescribir (corrida, agente) no duplica fila")
        self.assertEqual(ck["x"]["resumen"], "v2", "la fila queda con el ultimo valor")

        self.assertEqual(limpiar_checkpoints(corrida), 1)
        self.assertEqual(obtener_checkpoints(corrida), {})


if __name__ == "__main__":
    unittest.main()
