"""
core/log_config.py — Configuración de logging con rotación automática (self-healing).

Self-healing: si sistema.log supera MAX_BYTES se rota ANTES del análisis de métricas,
sin perder el handler activo (el RotatingFileHandler lo hace internamente en cada write).
"""
import logging
import shutil
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from pythonjsonlogger import jsonlogger
from core.path_manager import data_path

_LIBS_EXTERNAS = ('httpcore', 'httpx', 'google_genai', 'urllib3', 'asyncio')

# ── Límites de rotación ────────────────────────────────────────────────────────
MAX_BYTES    = 10 * 1024 * 1024   # 10 MB por fichero
BACKUP_COUNT = 5                   # sistema.log → sistema.log.1 … .5

_ROLLOVER_REINTENTOS = 3
_ROLLOVER_ESPERA_S   = 0.1


class RotatingFileHandlerSeguro(RotatingFileHandler):
    """RotatingFileHandler defensivo para Windows (2026-07-28).

    En Windows, doRollover() lanza PermissionError [WinError 32] si otro proceso
    (ej. el Dashboard UI leyendo sistema.log) mantiene el archivo abierto durante
    el rename. Ese fallo JAMAS debe propagarse al que emite el log (el
    orquestador). Se reintenta un par de veces (el lock suele ser breve) y, si
    aun no se puede, se re-abre el stream y se sigue escribiendo en el archivo
    actual (crece un poco de mas; se rotara en el proximo intento exitoso).
    """

    def doRollover(self) -> None:
        for intento in range(_ROLLOVER_REINTENTOS):
            try:
                super().doRollover()
                return
            except OSError as exc:   # PermissionError [WinError 32] incluido
                if intento < _ROLLOVER_REINTENTOS - 1:
                    time.sleep(_ROLLOVER_ESPERA_S)
                    continue
                # Ultimo intento fallido: degradar con gracia, NUNCA propagar.
                # doRollover cierra el stream antes de renombrar -> re-abrirlo
                # para que emit() pueda seguir escribiendo sin caer en un
                # bucle de handleError por stream=None.
                if self.stream is None:
                    try:
                        self.stream = self._open()
                    except OSError:
                        pass
                import sys
                print(f"[log_config] rotacion diferida (archivo en uso): {exc}",
                      file=sys.stderr)


def configurar_logging(
    nivel_consola: int = logging.WARNING,
    nivel_archivo: int = logging.DEBUG,
    ruta_log: Path | str | None = None,
) -> None:
    """
    Inicializa el logging raíz con:
      - Consola: texto simple, nivel WARNING por defecto.
      - Archivo:  JSON estructurado + RotatingFileHandler (10 MB × 5 copias).
    """
    ruta_log = Path(ruta_log) if ruta_log else data_path("logs/sistema.log")
    ruta_log.parent.mkdir(parents=True, exist_ok=True)

    json_fmt = jsonlogger.JsonFormatter(
        fmt='%(asctime)s %(levelname)s %(name)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        rename_fields={
            'asctime':   'timestamp',
            'levelname': 'level',
            'name':      'logger',
        },
        json_ensure_ascii=False,
    )
    texto_fmt = logging.Formatter('%(levelname)s — %(message)s')

    raiz = logging.getLogger()
    raiz.setLevel(logging.DEBUG)

    consola = logging.StreamHandler()
    consola.setLevel(nivel_consola)
    consola.setFormatter(texto_fmt)

    # RotatingFileHandlerSeguro — rota al superar MAX_BYTES; una rotacion que
    # falla por archivo bloqueado (WinError 32, Dashboard leyendo) NO propaga.
    archivo = RotatingFileHandlerSeguro(
        str(ruta_log),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding='utf-8',
    )
    archivo.setLevel(nivel_archivo)
    archivo.setFormatter(json_fmt)

    raiz.addHandler(consola)
    raiz.addHandler(archivo)

    for lib in _LIBS_EXTERNAS:
        logging.getLogger(lib).setLevel(logging.WARNING)


def rotar_log_si_necesario(
    ruta_log: Path | str | None = None,
    max_bytes: int = MAX_BYTES,
) -> bool:
    """
    Self-healing preventivo: llámalo ANTES de leer el log para análisis.

    Si el archivo es mayor que `max_bytes`, fuerza una rotación manual
    (copia a .bak, vacía el original) y devuelve True.
    No toca el RotatingFileHandler activo — solo mueve bytes en disco.
    """
    ruta = Path(ruta_log) if ruta_log else data_path("logs/sistema.log")
    if not ruta.exists():
        return False

    tam = ruta.stat().st_size
    if tam <= max_bytes:
        return False

    destino = ruta.with_suffix(ruta.suffix + ".bak")
    try:
        shutil.copy2(str(ruta), str(destino))
        ruta.write_bytes(b"")  # vaciar sin borrar (el handler sigue escribiendo)
        logging.getLogger(__name__).info(
            "Self-healing: log rotado manualmente (%s MB → %s)",
            round(tam / 1_048_576, 1), destino.name,
        )
        return True
    except OSError as e:
        logging.getLogger(__name__).warning("No se pudo rotar el log: %s", e)
        return False
