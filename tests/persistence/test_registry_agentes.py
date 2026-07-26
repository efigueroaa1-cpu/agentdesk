# -*- coding: utf-8 -*-
"""
tests/persistence/test_registry_agentes.py — Red de seguridad del ciclo de
vida de agentes (2026-07-26, pre-extraccion del RegistryMixin).

El CRUD de agentes del Orquestador (crear/eliminar/actualizar/reload) NO tenia
tests -- se extrae a core/orchestrator_registry.py como mixin, asi que primero
se caracteriza su comportamiento (crear -> persiste, actualizar -> valida,
eliminar -> quita, reload -> re-lee) para que la extraccion no pueda romperlo
en silencio.

Correr:  python -m unittest tests.persistence.test_registry_agentes -v
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from core.orchestrator import AgentBase, Orquestador


def _run(coro):
    return asyncio.run(coro)


_CFG_BASE = {
    "orquestador": {"max_agentes_paralelo": 2},
    "agents": [
        {"id": "agente_base_01", "nombre": "Base", "tipo_ia": "general",
         "area": "General", "modelo": "groq:llama-3.1-8b-instant",
         "temperatura": 0.4, "idioma": "español", "prompt_base": "base"},
    ],
}


class TestRegistryCicloVida(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._cfg_path = Path(self._dir.name) / "config.json"
        self._cfg_path.write_text(json.dumps(_CFG_BASE), encoding="utf-8")

        orq = object.__new__(Orquestador)            # sin __init__ (no red/genai)
        orq._config_path = str(self._cfg_path)
        orq._client = None                           # AgentBase solo lo guarda
        orq._model_name_global = "groq:llama-3.1-8b-instant"
        orq.config = json.loads(self._cfg_path.read_text(encoding="utf-8"))
        orq.agentes = {a["id"]: AgentBase(a, None, orq._model_name_global)
                       for a in orq.config["agents"]}
        self.orq = orq

    def tearDown(self):
        self._dir.cleanup()

    def _config_en_disco(self):
        return json.loads(self._cfg_path.read_text(encoding="utf-8"))

    def test_01_crear_agente_persiste_en_memoria_y_disco(self):
        ok = _run(self.orq.crear_nuevo_agente({"nombre": "Analista X", "area": "Finanzas"}))
        self.assertTrue(ok)
        nuevos = [a for a in self.orq.agentes if a != "agente_base_01"]
        self.assertEqual(len(nuevos), 1)
        ids_disco = [a["id"] for a in self._config_en_disco()["agents"]]
        self.assertIn(nuevos[0], ids_disco, "el agente nuevo debe quedar en config.json")

    def test_02_crear_sin_nombre_se_rechaza(self):
        self.assertFalse(_run(self.orq.crear_nuevo_agente({"area": "X"})))

    def test_03_eliminar_agente_quita_de_memoria_y_disco(self):
        ok = _run(self.orq.eliminar_agente("agente_base_01"))
        self.assertTrue(ok)
        self.assertNotIn("agente_base_01", self.orq.agentes)
        self.assertEqual(self._config_en_disco()["agents"], [])

    def test_04_eliminar_inexistente_devuelve_false(self):
        self.assertFalse(_run(self.orq.eliminar_agente("no_existe")))

    def test_05_actualizar_agente_valido_persiste(self):
        ok = _run(self.orq.actualizar_agente("agente_base_01", {"temperatura": 0.9}))
        self.assertTrue(ok)
        ag_disco = next(a for a in self._config_en_disco()["agents"] if a["id"] == "agente_base_01")
        self.assertEqual(ag_disco["temperatura"], 0.9)

    def test_06_reload_relee_config_del_disco(self):
        # cambio el archivo por fuera y verifico que reload lo toma
        cfg = self._config_en_disco()
        cfg["agents"][0]["idioma"] = "english"
        self._cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        actualizados = self.orq.reload_agente("agente_base_01")
        self.assertIn("agente_base_01", actualizados)
        self.assertEqual(self.orq.agentes["agente_base_01"].idioma, "english")


if __name__ == "__main__":
    unittest.main()
