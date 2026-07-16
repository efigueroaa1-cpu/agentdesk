# -*- coding: utf-8 -*-
"""
tests/sandbox/test_docker_runner.py — Sandbox de Grado Industrial (Fase 13, ADR-0011).

Verifica DockerRunner: comandos que corren dentro de un contenedor efímero
(sin red, no-root, límites de CPU/RAM). Los tests que requieren un
contenedor REAL se saltan con gracia si el binario `docker` no está
instalado — es una dependencia externa opcional (ADR-0011), no debe romper
el gate en un entorno sin Docker.

Correr:  python -m unittest tests.sandbox.test_docker_runner -v
"""
import asyncio
import sys
import unittest

from core.services.sandbox_service import DockerRunner


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=90))


class TestDockerRunnerValidaciones(unittest.TestCase):
    """Estas SIEMPRE corren — no requieren Docker instalado."""

    def test_01_shell_como_string_rechazada(self):
        with self.assertRaises(ValueError):
            _run(DockerRunner().ejecutar("python -c print(1)"))

    def test_02_comando_vacio_rechazado(self):
        with self.assertRaises(ValueError):
            _run(DockerRunner().ejecutar([]))

    @unittest.skipIf(DockerRunner.disponible(), "Docker SI esta instalado — no aplica")
    def test_03_degrada_con_gracia_sin_docker(self):
        """Sin el binario docker, ejecutar() falla con un mensaje claro, no un crash."""
        with self.assertRaises(RuntimeError) as ctx:
            _run(DockerRunner().ejecutar([sys.executable, "-c", "print(1)"]))
        self.assertIn("docker", str(ctx.exception).lower())


@unittest.skipUnless(DockerRunner.disponible(), "Docker no esta instalado en este entorno")
class TestDockerRunnerContenedorReal(unittest.TestCase):
    """Requieren Docker real — se saltan con gracia si no esta disponible."""

    def test_04_ejecucion_aislada_en_contenedor(self):
        r = _run(DockerRunner(imagen="python:3.13-slim").ejecutar(
            ["python3", "-c", "print('hola-desde-el-contenedor')"]))
        self.assertTrue(r.ok)
        self.assertIn("hola-desde-el-contenedor", r.stdout)

    def test_05_sin_red_dentro_del_contenedor(self):
        """--network none: cualquier intento de red debe fallar."""
        r = _run(DockerRunner(imagen="python:3.13-slim", timeout_s=20).ejecutar([
            "python3", "-c",
            "import socket; socket.create_connection(('8.8.8.8', 53), timeout=3)",
        ]))
        self.assertFalse(r.ok, "Sin --network none, el contenedor tendria salida a internet")

    def test_06_timeout_mata_el_contenedor(self):
        r = _run(DockerRunner(imagen="python:3.13-slim", timeout_s=2).ejecutar(
            ["python3", "-c", "import time; time.sleep(30)"]))
        self.assertEqual(r.motivo_kill, "timeout")
        self.assertFalse(r.ok)


if __name__ == "__main__":
    unittest.main()
