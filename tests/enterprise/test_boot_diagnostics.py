# -*- coding: utf-8 -*-
"""
tests/enterprise/test_boot_diagnostics.py — Diagnóstico de Arranque
Enterprise (Fase 18, ADR-0016).

Criterios: AGENTDESK_DB_URL con credenciales de base de datos por defecto,
vacías o triviales (usuario == clave) es un CRÍTICO (Fail-Hard); sin la
variable, o apuntando a sqlite:///, no se evalúa (modo desktop válido por
diseño, ADR-0005). El Diagnóstico de Arranque Enterprise compone ese
chequeo con el ya existente de JWT/MASTER_PASSWORD_HASH (ADR-0008) sin
duplicar su lógica.

Usa una base SQLite temporal — no toca la DB real del usuario.
"""
import os
import tempfile
import unittest
from pathlib import Path

import core.database as db
from core.services.boot_diagnostics_service import (
    _validar_db_url,
    diagnostico_arranque_sistema,
)


class TestValidarDbUrl(unittest.TestCase):

    def setUp(self):
        self._original = os.environ.pop("AGENTDESK_DB_URL", None)

    def tearDown(self):
        if self._original is not None:
            os.environ["AGENTDESK_DB_URL"] = self._original
        else:
            os.environ.pop("AGENTDESK_DB_URL", None)

    def test_01_sin_variable_no_es_critico(self):
        """Modo desktop zero-config (SQLite por defecto): valido por diseño."""
        self.assertEqual(_validar_db_url(), [])

    def test_02_sqlite_explicito_no_se_evalua(self):
        os.environ["AGENTDESK_DB_URL"] = "sqlite:///./algo.db"
        self.assertEqual(_validar_db_url(), [])

    def test_03_credencial_por_defecto_es_critico(self):
        os.environ["AGENTDESK_DB_URL"] = "postgresql://postgres:postgres@10.0.0.5:5432/agentdesk"
        errores = _validar_db_url()
        self.assertTrue(errores)
        self.assertIn("por defecto", errores[0])

    def test_04_clave_vacia_es_critico(self):
        os.environ["AGENTDESK_DB_URL"] = "postgresql://planta_svc@10.0.0.5:5432/agentdesk"
        self.assertTrue(_validar_db_url())

    def test_05_usuario_igual_clave_es_critico(self):
        os.environ["AGENTDESK_DB_URL"] = "postgresql://svc_planta:svc_planta@10.0.0.5:5432/agentdesk"
        self.assertTrue(_validar_db_url())

    def test_06_credencial_fuerte_pasa(self):
        os.environ["AGENTDESK_DB_URL"] = "postgresql://svc_planta_ci:X7!qP2vR9zL4mK8@10.0.0.5:5432/agentdesk"
        self.assertEqual(_validar_db_url(), [])

    def test_07_url_malformada_reporta_error_sin_reventar(self):
        os.environ["AGENTDESK_DB_URL"] = "postgresql://[usuario-mal-formado"
        errores = _validar_db_url()
        self.assertTrue(errores)


class TestDiagnosticoArranqueSistema(unittest.TestCase):
    """Composicion: JWT (ADR-0008, reusado) + AGENTDESK_DB_URL (ADR-0016, nuevo)."""

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "boot_diag_test.db")

    def setUp(self):
        self._db_url_original = os.environ.pop("AGENTDESK_DB_URL", None)
        self._jwt_original    = os.environ.pop("AGENTDESK_JWT_SECRET", None)

    def tearDown(self):
        for var, val in (("AGENTDESK_DB_URL", self._db_url_original),
                          ("AGENTDESK_JWT_SECRET", self._jwt_original)):
            if val is not None:
                os.environ[var] = val
            else:
                os.environ.pop(var, None)

    def test_08_compone_jwt_y_db_url_en_una_sola_lista_de_criticos(self):
        """JWT debil Y AGENTDESK_DB_URL insegura -> ambos criticos en la misma respuesta."""
        os.environ["AGENTDESK_JWT_SECRET"] = "corto"
        os.environ["AGENTDESK_DB_URL"]     = "postgresql://postgres:postgres@10.0.0.5:5432/agentdesk"
        salud = diagnostico_arranque_sistema()
        self.assertTrue(any("JWT_SECRET" in c for c in salud["criticos"]))
        self.assertTrue(any("AGENTDESK_DB_URL" in c for c in salud["criticos"]))

    def test_09_configuracion_solida_no_genera_criticos(self):
        os.environ["AGENTDESK_JWT_SECRET"] = "z" * 40
        os.environ["AGENTDESK_DB_URL"]     = "postgresql://svc_planta_ci:X7!qP2vR9zL4mK8@10.0.0.5:5432/agentdesk"
        salud = diagnostico_arranque_sistema()
        self.assertEqual(salud["criticos"], [])


if __name__ == "__main__":
    unittest.main()
