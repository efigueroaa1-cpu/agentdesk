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
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

from core.services.sandbox_service import DockerRunner


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=90))


class TestDockerRunnerDisponibleModoContenedor(unittest.TestCase):
    """disponible() debe verificar que el DAEMON sirve contenedores Linux, no
    solo que el binario 'docker' este en PATH (2026-07-21, hallazgo real en
    CI): el runner windows-latest de GitHub Actions trae el CLI de Docker
    pero en modo Windows containers -- shutil.which('docker') da True, y
    'python:3.13-slim' (imagen Linux) fallaba en vez de saltarse con gracia.
    """

    @patch("shutil.which", return_value=r"C:\Program Files\Docker\docker.exe")
    @patch("subprocess.run")
    def test_01_daemon_en_modo_linux_disponible(self, m_run, _m_which):
        m_run.return_value = MagicMock(returncode=0, stdout="linux\n")
        self.assertTrue(DockerRunner.disponible())

    @patch("shutil.which", return_value=r"C:\Program Files\Docker\docker.exe")
    @patch("subprocess.run")
    def test_02_daemon_en_modo_windows_no_disponible(self, m_run, _m_which):
        """El caso real de GitHub Actions windows-latest."""
        m_run.return_value = MagicMock(returncode=0, stdout="windows\n")
        self.assertFalse(DockerRunner.disponible())

    @patch("shutil.which", return_value=None)
    def test_03_binario_ausente_no_disponible(self, _m_which):
        self.assertFalse(DockerRunner.disponible())

    @patch("shutil.which", return_value=r"C:\Program Files\Docker\docker.exe")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=5))
    def test_04_daemon_no_responde_no_disponible(self, _m_run, _m_which):
        """CLI presente pero el daemon no arranco/no responde -- nunca crashea."""
        self.assertFalse(DockerRunner.disponible())

    @patch("shutil.which", return_value=r"C:\Program Files\Docker\docker.exe")
    @patch("subprocess.run")
    def test_05_comando_falla_no_disponible(self, m_run, _m_which):
        m_run.return_value = MagicMock(returncode=1, stdout="")
        self.assertFalse(DockerRunner.disponible())


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
