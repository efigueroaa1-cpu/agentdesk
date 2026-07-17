# -*- coding: utf-8 -*-
"""
tests/harnesses/test_habilidades_harness.py — SkillHarness (Fase 25, ADR-0023).

El HAT "habilidades" inyecta recetas aprendidas relevantes al mensaje,
siempre dentro del scope user_id (+ proyecto_id) — el know-how de un
usuario jamas llega a otro, y sin user_id no se consulta nada.
"""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import core.vector_store as vs
from core.services.harness_service import HarnessService, SkillHarness
from core.vector_store import VectorStoreHermes


def _corre(coro):
    return asyncio.run(coro)


def _sembrar_receta(tmp: Path, user_id: str) -> dict:
    """Receta en skills/ + su indice en Hermes (lo que hace extraer_habilidad)."""
    receta = {
        "slug": "purga-de-bomba", "nombre": "Purga de Bomba 5",
        "descripcion": "Procedimiento de purga semanal de la bomba 5",
        "secuencia_herramientas": ["leer_sensor", "abrir_valvula", "registrar_evento"],
        "ejemplo": {"prompt": "como purgo la bomba 5 del circuito", "respuesta": "ok",
                    "agente_id": "ag_mantenimiento"},
        "user_id": user_id, "creada": time.time(), "version": 1,
    }
    skills_dir = tmp / "AgentDesk" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "purga-de-bomba.json").write_text(
        json.dumps(receta, ensure_ascii=False), encoding="utf-8")
    vs.hermes().guardar(
        f"Habilidad: {receta['nombre']}. {receta['descripcion']}. "
        f"Herramientas: {' '.join(receta['secuencia_herramientas'])}. "
        f"Ejemplo: {receta['ejemplo']['prompt']}",
        user_id=user_id, proyecto_id="global", tipo="habilidad",
    )
    return receta


class TestSkillHarness(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        cls._appdata_original = os.environ.get("APPDATA")
        cls._tmp = Path(tempfile.mkdtemp(prefix="agentdesk_skillhat_"))
        os.environ["APPDATA"] = str(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        if cls._appdata_original is not None:
            os.environ["APPDATA"] = cls._appdata_original

    def setUp(self):
        vs._instancia = VectorStoreHermes(self._tmp / "memoria_vectorial.db")

    def tearDown(self):
        vs._instancia = None

    async def test_01_inyecta_receta_relevante_para_su_usuario(self):
        _sembrar_receta(self._tmp, "operador_a")
        harness = SkillHarness()
        harness.attach("ag_otro", {})
        contexto = await harness.apply_hooks("pre", {
            "agente_id": "ag_otro",
            "mensaje": "necesito purgar la bomba 5, cual es el procedimiento?",
            "user_id": "operador_a",
        })
        habilidades = contexto.get("habilidades", "")
        self.assertIn("Purga de Bomba 5", habilidades)
        self.assertIn("leer_sensor -> abrir_valvula -> registrar_evento", habilidades)

    async def test_02_no_cruza_usuarios(self):
        _sembrar_receta(self._tmp, "operador_a")
        harness = SkillHarness()
        harness.attach("ag_otro", {})
        contexto = await harness.apply_hooks("pre", {
            "agente_id": "ag_otro",
            "mensaje": "necesito purgar la bomba 5, cual es el procedimiento?",
            "user_id": "operador_b",
        })
        self.assertNotIn("Purga de Bomba 5", contexto.get("habilidades", ""))

    async def test_03_sin_user_id_fail_closed(self):
        _sembrar_receta(self._tmp, "operador_a")
        harness = SkillHarness()
        harness.attach("ag_otro", {})
        contexto = await harness.apply_hooks("pre", {
            "agente_id": "ag_otro",
            "mensaje": "necesito purgar la bomba 5",
        })
        self.assertNotIn("habilidades", contexto)

    async def test_04_mensaje_sin_relacion_no_inyecta_nada(self):
        _sembrar_receta(self._tmp, "operador_a")
        harness = SkillHarness()
        harness.attach("ag_otro", {})
        contexto = await harness.apply_hooks("pre", {
            "agente_id": "ag_otro",
            "mensaje": "cual es el estado del presupuesto trimestral de marketing?",
            "user_id": "operador_a",
        })
        self.assertNotIn("Purga de Bomba 5", contexto.get("habilidades", ""))

    async def test_05_registrado_en_harness_service_y_fase_post_noop(self):
        self.assertIn("habilidades", HarnessService._REGISTRO)
        harness = SkillHarness()
        contexto = await harness.apply_hooks("post", {"respuesta": "hola"})
        self.assertEqual(contexto, {"respuesta": "hola"})


if __name__ == "__main__":
    unittest.main()
