# -*- coding: utf-8 -*-
"""
tests/observability/test_log_rotacion_segura.py — Rotacion de log resiliente a
WinError 32 (2026-07-28).

En Windows, RotatingFileHandler.doRollover() lanza PermissionError [WinError 32]
si otro proceso (Dashboard UI) mantiene sistema.log abierto durante la rotacion.
Ese fallo NO debe propagarse ni bloquear al orquestador: RotatingFileHandlerSeguro
reintenta y, si aun no puede, sigue escribiendo en el archivo actual (crece un
poco) sin lanzar.

Correr:  python -m unittest tests.observability.test_log_rotacion_segura -v
"""
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.log_config import RotatingFileHandlerSeguro


class TestRotacionSegura(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._log = Path(self._dir.name) / "sistema.log"

    def tearDown(self):
        for h in list(logging.getLogger("_rot_test").handlers):
            h.close()
            logging.getLogger("_rot_test").removeHandler(h)
        self._dir.cleanup()

    def _handler(self):
        h = RotatingFileHandlerSeguro(str(self._log), maxBytes=200, backupCount=2,
                                      encoding="utf-8")
        h.setFormatter(logging.Formatter("%(message)s"))
        return h

    def test_01_winerror32_en_rollover_no_propaga(self):
        """Si doRollover falla siempre (archivo bloqueado), emit NO lanza y el
        log sigue registrando en el archivo actual."""
        h = self._handler()
        log = logging.getLogger("_rot_test")
        log.setLevel(logging.DEBUG)
        log.addHandler(h)

        # doRollover del padre siempre falla con el WinError 32
        log.info("relleno inicial (Python 3.13 no rota un archivo vacio)")
        with patch("logging.handlers.RotatingFileHandler.doRollover",
                   side_effect=PermissionError(32, "El proceso no tiene acceso")):
            for i in range(8):   # varios cruces de maxBytes, rollover fallando
                log.info("linea de log numero %d con relleno para pasar 200 bytes", i)

        # no exploto y el archivo tiene contenido
        self.assertTrue(self._log.exists())
        self.assertGreater(self._log.stat().st_size, 0)

    def test_02_reintenta_y_logra_rotar(self):
        """Falla las primeras veces, luego el archivo se libera y rota OK."""
        llamadas = {"n": 0}
        real = logging.handlers.RotatingFileHandler.doRollover

        def _flaky(self):
            llamadas["n"] += 1
            if llamadas["n"] <= 2:
                raise PermissionError(32, "bloqueado")
            return real(self)

        h = self._handler()
        log = logging.getLogger("_rot_test")
        log.setLevel(logging.DEBUG)
        log.addHandler(h)
        # Python 3.13 (gh-116263) nunca rota un archivo VACIO: se puebla primero
        # y la 2da escritura dispara el rollover (que reintenta via _flaky).
        log.info("relleno inicial para que el archivo no este vacio")
        with patch("logging.handlers.RotatingFileHandler.doRollover", _flaky):
            log.info("x" * 300)   # dispara un rollover que reintenta
        self.assertGreaterEqual(llamadas["n"], 1)

    def test_03_stream_utilizable_tras_fallo_de_rotacion(self):
        """Tras un rollover fallido el stream queda abierto: se sigue escribiendo."""
        h = self._handler()
        with patch("logging.handlers.RotatingFileHandler.doRollover",
                   side_effect=PermissionError(32, "bloqueado")):
            h.doRollover()   # no lanza
        # el handler puede emitir despues del fallo
        rec = logging.LogRecord("_rot_test", logging.INFO, __file__, 1,
                                "post-fallo", None, None)
        h.emit(rec)   # no lanza
        h.close()
        self.assertIn("post-fallo", self._log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
