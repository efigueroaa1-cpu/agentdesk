# -*- coding: utf-8 -*-
"""
tests/resilience/test_json_extraccion.py — Extraccion tolerante de JSON de
salida LLM (2026-07-26, Modo Faena).

Los modelos locales chicos (Llama 3.2 via Ollama) suelen envolver el JSON del
reporte en prosa ("Aqui esta el reporte: {...}") o en fences markdown, o
agregan texto despues del objeto. El parseo viejo solo quitaba fences y
json.loads fallaba -> el Contador ICI aborto con 'JSON invalido tras 2
intentos' en la corrida offline real. extraer_json_objeto() aisla el objeto
JSON balanceado del ruido circundante.

Correr:  python -m unittest tests.resilience.test_json_extraccion -v
"""
import json
import unittest

from core.schemas import extraer_json_objeto


class TestExtraccionJson(unittest.TestCase):

    def test_01_json_pelado_pasa_intacto(self):
        crudo = '{"resumen": "ok", "kpis": {"a": 1}}'
        self.assertEqual(json.loads(extraer_json_objeto(crudo)), json.loads(crudo))

    def test_02_fences_markdown_se_remueven(self):
        crudo = '```json\n{"resumen": "ok"}\n```'
        self.assertEqual(json.loads(extraer_json_objeto(crudo)), {"resumen": "ok"})

    def test_03_prosa_antes_del_objeto(self):
        crudo = 'Claro, aqui esta el reporte solicitado:\n{"resumen": "ok"}'
        self.assertEqual(json.loads(extraer_json_objeto(crudo)), {"resumen": "ok"})

    def test_04_prosa_despues_del_objeto(self):
        crudo = '{"resumen": "ok"}\n\nEspero que sea util. Avisame si necesitas mas.'
        self.assertEqual(json.loads(extraer_json_objeto(crudo)), {"resumen": "ok"})

    def test_05_prosa_a_ambos_lados_y_fences(self):
        crudo = 'Reporte:\n```json\n{"resumen": "ok", "n": 3}\n```\nFin del reporte.'
        self.assertEqual(json.loads(extraer_json_objeto(crudo)), {"resumen": "ok", "n": 3})

    def test_06_llaves_dentro_de_strings_no_confunden(self):
        crudo = 'Nota: {"resumen": "usa {llaves} en el texto", "ok": true} listo'
        obj = json.loads(extraer_json_objeto(crudo))
        self.assertEqual(obj["resumen"], "usa {llaves} en el texto")
        self.assertTrue(obj["ok"])

    def test_07_objeto_anidado_se_balancea_completo(self):
        crudo = 'aqui: {"a": {"b": {"c": 1}}, "d": 2} gracias'
        self.assertEqual(json.loads(extraer_json_objeto(crudo)), {"a": {"b": {"c": 1}}, "d": 2})

    def test_08_sin_llaves_devuelve_texto_limpio_que_json_rechaza(self):
        crudo = 'No puedo generar el reporte ahora.'
        salida = extraer_json_objeto(crudo)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(salida)


if __name__ == "__main__":
    unittest.main()
