# -*- coding: utf-8 -*-
"""
tests/sandbox/test_subprocess_runner.py — Blindaje de Ejecución (Fase 7).

Verifica el entorno Zero-Trust del SubprocessRunner: shell prohibida, lista
blanca de ejecutables, entorno mínimo sin API keys, timeout con kill duro.

Correr:  python -m unittest tests.sandbox.test_subprocess_runner -v
"""
import asyncio
import os
import sys
import unittest

from core.services.sandbox_service import SubprocessRunner


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=60))


class TestSubprocessRunner(unittest.TestCase):

    def test_01_ejecucion_normal(self):
        """Un script sano corre y su salida vuelve truncable y decodificada."""
        r = _run(SubprocessRunner().ejecutar(
            [sys.executable, "-c", "print('hola-sandbox')"]))
        self.assertTrue(r.ok)
        self.assertEqual(r.exit_code, 0)
        self.assertIn("hola-sandbox", r.stdout)

    def test_02_shell_como_string_rechazada(self):
        """Pasar un string (uso tipo shell) es rechazado ANTES de ejecutar."""
        with self.assertRaises(ValueError):
            _run(SubprocessRunner().ejecutar("python -c print(1)"))

    def test_03_ejecutable_fuera_de_lista_blanca_rechazado(self):
        """Solo los ejecutables de la lista blanca pueden lanzarse."""
        with self.assertRaises(ValueError):
            _run(SubprocessRunner().ejecutar(["cmd.exe", "/c", "dir"]))
        with self.assertRaises(ValueError):
            _run(SubprocessRunner().ejecutar(["powershell.exe", "-Command", "ls"]))

    def test_04_entorno_minimo_sin_api_keys(self):
        """El hijo NO hereda las API keys ni el entorno del proceso padre."""
        os.environ.setdefault("GEMINI_API_KEY", "secreto-de-prueba")
        r = _run(SubprocessRunner().ejecutar([
            sys.executable, "-c",
            "import os; print(sorted(k for k in os.environ if 'KEY' in k.upper() or 'TOKEN' in k.upper()))",
        ]))
        self.assertTrue(r.ok)
        self.assertEqual(r.stdout.strip(), "[]",
                         f"El sandbox filtro variables sensibles: {r.stdout}")

    def test_05_timeout_mata_el_proceso(self):
        """Un script colgado se termina con kill duro y queda marcado."""
        runner = SubprocessRunner(timeout_s=2.0)
        r = _run(runner.ejecutar(
            [sys.executable, "-c", "import time; time.sleep(60)"]))
        self.assertFalse(r.ok)
        self.assertEqual(r.motivo_kill, "timeout")
        self.assertLess(r.duracion_s, 10)

    def test_06_fallo_del_script_no_compromete_al_host(self):
        """Un crash del script devuelve exit_code != 0, sin excepción al host."""
        r = _run(SubprocessRunner().ejecutar(
            [sys.executable, "-c", "raise RuntimeError('boom')"]))
        self.assertFalse(r.ok)
        self.assertNotEqual(r.exit_code, 0)
        self.assertIn("boom", r.stderr)


if __name__ == "__main__":
    unittest.main()
