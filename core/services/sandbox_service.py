"""
core/services/sandbox_service.py — Ejecución Zero-Trust de herramientas
(Fase 7, Sandboxing Fase 1).

SubprocessRunner endurecido para que un script disparado por un agente no
pueda comprometer el host:
  - shell=False SIEMPRE (la API solo acepta listas de argumentos; no hay
    forma de inyectar un string a la shell).
  - Lista blanca de ejecutables (por defecto solo el Python del sistema).
  - Entorno mínimo: se construye desde cero — NINGUNA API key ni variable
    del proceso padre se filtra al hijo.
  - Directorio de trabajo aislado bajo el data dir (sandbox/).
  - Límite de tiempo (kill duro) y de memoria (vigilancia con psutil si está
    disponible; sin psutil se degrada a solo-timeout dejando aviso).
  - Salida truncada (max_salida) para no inundar memoria ni logs.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Variables imprescindibles para que un proceso arranque en Windows/POSIX.
# Deliberadamente NO se copia os.environ (ahí viven las API keys).
_ENV_MINIMO_KEYS = ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT")


def _entorno_minimo() -> dict[str, str]:
    env = {k: os.environ[k] for k in _ENV_MINIMO_KEYS if k in os.environ}
    env["PATH"] = os.path.dirname(sys.executable)   # solo el dir del intérprete
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@dataclass
class ResultadoSandbox:
    ok:          bool
    exit_code:   int | None
    stdout:      str
    stderr:      str
    duracion_s:  float
    motivo_kill: str = ""      # "" | "timeout" | "memoria"

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "exit_code": self.exit_code,
            "stdout": self.stdout, "stderr": self.stderr,
            "duracion_s": self.duracion_s, "motivo_kill": self.motivo_kill,
        }


@dataclass
class SubprocessRunner:
    """Ejecutor Zero-Trust. Uso: await SubprocessRunner().ejecutar([...])."""

    timeout_s:      float = 30.0
    max_memoria_mb: int   = 256
    max_salida:     int   = 16_000
    ejecutables:    tuple[str, ...] = field(default_factory=lambda: (sys.executable,))

    def _dir_sandbox(self) -> Path:
        from core.path_manager import data_path
        d = data_path("sandbox")
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def ejecutar(self, comando: list[str]) -> ResultadoSandbox:
        """
        Ejecuta `comando` (lista, nunca string) en el entorno aislado.
        Lanza ValueError si el ejecutable no está en la lista blanca o si
        el comando llega como string (intento de uso tipo shell).
        """
        if isinstance(comando, (str, bytes)):
            raise ValueError("El comando debe ser una lista de argumentos (shell prohibida).")
        if not comando:
            raise ValueError("Comando vacío.")
        ejecutable = str(comando[0])
        if ejecutable not in self.ejecutables:
            raise ValueError(
                f"Ejecutable no autorizado: '{ejecutable}'. "
                f"Lista blanca: {list(self.ejecutables)}"
            )

        loop = asyncio.get_running_loop()
        t0   = loop.time()
        proc = await asyncio.create_subprocess_exec(   # shell=False por diseño
            *comando,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            cwd=str(self._dir_sandbox()),
            env=_entorno_minimo(),
        )

        vigilante = asyncio.create_task(self._vigilar_memoria(proc))
        motivo_kill = ""
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            stdout_b, stderr_b, motivo_kill = b"", b"", "timeout"
        finally:
            if not vigilante.done():
                vigilante.cancel()

        if vigilante.done() and not vigilante.cancelled() and vigilante.result():
            motivo_kill = "memoria"

        duracion = round(loop.time() - t0, 3)
        resultado = ResultadoSandbox(
            ok=(proc.returncode == 0 and not motivo_kill),
            exit_code=proc.returncode,
            stdout=stdout_b.decode("utf-8", errors="replace")[: self.max_salida],
            stderr=stderr_b.decode("utf-8", errors="replace")[: self.max_salida],
            duracion_s=duracion,
            motivo_kill=motivo_kill,
        )
        if motivo_kill:
            logger.warning("SANDBOX: proceso terminado por %s — cmd=%s dur=%.1fs",
                           motivo_kill, comando[:3], duracion)
        return resultado

    async def _vigilar_memoria(self, proc) -> bool:
        """Mata el proceso si supera max_memoria_mb. True si lo mató."""
        try:
            import psutil
        except ImportError:
            logger.debug("psutil no instalado — límite de memoria no vigilado (solo timeout).")
            return False
        try:
            p = psutil.Process(proc.pid)
            limite = self.max_memoria_mb * 1024 * 1024
            while proc.returncode is None:
                if p.memory_info().rss > limite:
                    proc.kill()
                    return True
                await asyncio.sleep(0.1)
        except Exception:
            pass
        return False


@dataclass
class DockerRunner:
    """
    Ejecutor de Grado Industrial (ADR-0011): corre un comando dentro de un
    contenedor Docker EFÍMERO para aislamiento total del host — para
    herramientas de origen no confiable (código generado, scripts subidos)
    donde ni el entorno mínimo de SubprocessRunner alcanza.

    Contenedor: --rm (se autodestruye), --network none (sin red), usuario
    no-root (65534:65534), --cap-drop ALL, límites duros de CPU/RAM/PIDs,
    filesystem de solo lectura con /tmp efímero para trabajo. NINGUNA
    variable de entorno del host se propaga (no se usa -e en ningún caso).

    Degrada con gracia: si el binario `docker` no está instalado, ejecutar()
    lanza RuntimeError con un mensaje claro — nunca crashea el proceso host
    ni cae en silencio a ejecución sin aislar.
    """

    timeout_s:      float = 30.0
    max_memoria_mb: int   = 256
    max_cpus:       float = 1.0
    max_salida:     int   = 16_000
    imagen:         str   = "python:3.13-slim"

    @staticmethod
    def disponible() -> bool:
        import shutil
        return shutil.which("docker") is not None

    async def ejecutar(self, comando: list[str]) -> ResultadoSandbox:
        if isinstance(comando, (str, bytes)):
            raise ValueError("El comando debe ser una lista de argumentos (shell prohibida).")
        if not comando:
            raise ValueError("Comando vacío.")
        if not self.disponible():
            raise RuntimeError(
                "DockerRunner no disponible: el binario 'docker' no está instalado o "
                "no está en PATH. El sandbox Docker es opcional (ADR-0011) — usa "
                "SubprocessRunner si no necesitas aislamiento a nivel de contenedor."
            )

        nombre_contenedor = f"agentdesk-sbx-{uuid.uuid4().hex[:12]}"
        docker_cmd = [
            "docker", "run",
            "--rm",                                        # efímero
            "--name", nombre_contenedor,
            "--network", "none",                            # sin red
            "--user", "65534:65534",                        # nobody — no-root
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "64",
            "--memory", f"{self.max_memoria_mb}m",
            "--memory-swap", f"{self.max_memoria_mb}m",     # sin swap adicional
            "--cpus", str(self.max_cpus),
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",  # nosec B108 - ruta DENTRO del contenedor, no del host
            self.imagen,
            *comando,
        ]

        loop = asyncio.get_running_loop()
        t0   = loop.time()
        proc = await asyncio.create_subprocess_exec(   # shell=False por diseño
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )

        motivo_kill = ""
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            await self._matar_contenedor(nombre_contenedor)
            proc.kill()
            await proc.communicate()
            stdout_b, stderr_b, motivo_kill = b"", b"", "timeout"

        duracion  = round(loop.time() - t0, 3)
        resultado = ResultadoSandbox(
            ok=(proc.returncode == 0 and not motivo_kill),
            exit_code=proc.returncode,
            stdout=stdout_b.decode("utf-8", errors="replace")[: self.max_salida],
            stderr=stderr_b.decode("utf-8", errors="replace")[: self.max_salida],
            duracion_s=duracion,
            motivo_kill=motivo_kill,
        )
        if motivo_kill:
            logger.warning("SANDBOX-DOCKER: contenedor %s terminado por %s — dur=%.1fs",
                           nombre_contenedor, motivo_kill, duracion)
        return resultado

    @staticmethod
    async def _matar_contenedor(nombre: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "kill", nombre,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:
            pass
