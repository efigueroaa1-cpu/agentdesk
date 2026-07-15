# -*- coding: utf-8 -*-
"""
tests/enterprise/test_refresh_tokens.py — Blindaje Enterprise (Fase 10, ADR-0008).

Criterios: el access token expira solo (30 min) y la sesión se mantiene vía
refresh rotativo; el reuso de un refresh revocado revoca la familia (robo);
y el chequeo de arranque detecta secretos débiles y falta de credenciales.

Usa una base SQLite temporal — no toca la DB real del usuario.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

import core.database as db
from core.services.auth_service import (
    ACCESS_EXPIRE_MIN,
    AuthService,
    _get_secret,
    _hash_password,
)


class TestRefreshTokens(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "enterprise_test.db")
        from core.repositories.user_repository import SqlAlchemyUserRepository
        cls.repo = SqlAlchemyUserRepository()
        cls.repo.agregar("op.planta", _hash_password("clave-segura-9x!"), "supervisor")
        cls.svc = AuthService(repo=cls.repo)

    def test_01_login_entrega_access_corto_y_refresh(self):
        r = self.svc.login("op.planta", "clave-segura-9x!")
        self.assertIsNotNone(r)
        self.assertLessEqual(r["expires_in"], 30 * 60,
                             "El access token debe expirar en <=30 minutos")
        self.assertIn("refresh_token", r)
        self.assertGreater(len(r["refresh_token"]), 40)

    def test_02_access_expirado_es_invalido_pero_refresh_mantiene_sesion(self):
        """Criterio de éxito: la sesión sobrevive a la expiración del access."""
        import jwt
        # Access ya vencido (firmado con el secreto real)
        vencido = jwt.encode(
            {"sub": "op.planta", "role": "supervisor",
             "iat": time.time() - 3600, "exp": time.time() - 60},
            _get_secret(), algorithm="HS256",
        )
        self.assertIsNone(self.svc.verificar_token(vencido),
                          "Un access expirado debe quedar invalidado")

        sesion = self.svc.login("op.planta", "clave-segura-9x!")
        renovado = self.svc.refrescar(sesion["refresh_token"])
        self.assertIsNotNone(renovado, "El refresh debe mantener la sesión viva")
        datos = self.svc.verificar_token(renovado["token"])
        self.assertEqual(datos["sub"], "op.planta")

    def test_03_rotacion_un_solo_uso(self):
        """Cada refresh es de un solo uso: el canje entrega uno NUEVO."""
        sesion  = self.svc.login("op.planta", "clave-segura-9x!")
        primero = sesion["refresh_token"]
        r1 = self.svc.refrescar(primero)
        self.assertIsNotNone(r1)
        self.assertNotEqual(r1["refresh_token"], primero)
        # El ya usado quedó revocado
        self.assertIsNone(self.svc.refrescar(primero))

    def test_04_reuso_revocado_revoca_la_familia(self):
        """Reusar un token revocado delata robo: cae TODA la familia."""
        sesion  = self.svc.login("op.planta", "clave-segura-9x!")
        viejo   = sesion["refresh_token"]
        vigente = self.svc.refrescar(viejo)["refresh_token"]
        self.assertIsNone(self.svc.refrescar(viejo))     # reuso → robo detectado
        self.assertIsNone(self.svc.refrescar(vigente),
                          "Tras el reuso, la familia completa debe quedar revocada")

    def test_05_arranque_detecta_jwt_secret_debil(self):
        debil = Path(tempfile.mkdtemp()) / "jwt_secret.key"
        debil.write_text("changeme", encoding="utf-8")
        salud = self.svc.diagnostico_arranque(jwt_secret_path=debil)
        self.assertTrue(any("JWT_SECRET" in c for c in salud["criticos"]))

        fuerte = Path(tempfile.mkdtemp()) / "jwt_secret.key"
        fuerte.write_text("a" * 64, encoding="utf-8")
        salud2 = self.svc.diagnostico_arranque(jwt_secret_path=fuerte)
        self.assertEqual(salud2["criticos"], [])

    def test_06b_agentdesk_jwt_secret_tiene_prioridad_absoluta(self):
        """AGENTDESK_JWT_SECRET pisa jwt_secret.key: ni se lee el archivo."""
        original = os.environ.pop("AGENTDESK_JWT_SECRET", None)
        archivo_ignorado = Path(tempfile.mkdtemp()) / "jwt_secret.key"
        archivo_ignorado.write_text("c" * 64, encoding="utf-8")
        try:
            os.environ["AGENTDESK_JWT_SECRET"] = "d" * 40
            self.assertEqual(_get_secret(), "d" * 40)

            salud_fuerte = self.svc.diagnostico_arranque(jwt_secret_path=archivo_ignorado)
            self.assertEqual(salud_fuerte["criticos"], [])

            # token emitido y verificado íntegramente bajo el override, sin
            # tocar el secreto del archivo (que sigue siendo "cccc...").
            tok = self.svc.crear_token("op.planta", "supervisor")
            self.assertIsNotNone(self.svc.verificar_token(tok["token"]))

            os.environ["AGENTDESK_JWT_SECRET"] = "corto"
            salud_debil = self.svc.diagnostico_arranque(jwt_secret_path=archivo_ignorado)
            self.assertTrue(any("AGENTDESK_JWT_SECRET" in c for c in salud_debil["criticos"]))
        finally:
            if original is not None:
                os.environ["AGENTDESK_JWT_SECRET"] = original
            else:
                os.environ.pop("AGENTDESK_JWT_SECRET", None)

    def test_06_arranque_sin_credenciales_degrada_a_configuracion(self):
        class _RepoVacio:
            def contar(self):
                return 0

        original = os.environ.pop("MASTER_PASSWORD_HASH", None)
        try:
            svc = AuthService(repo=_RepoVacio())
            fuerte = Path(tempfile.mkdtemp()) / "jwt_secret.key"
            fuerte.write_text("b" * 64, encoding="utf-8")
            salud = svc.diagnostico_arranque(jwt_secret_path=fuerte)
            self.assertTrue(salud["modo_configuracion"])
            self.assertEqual(salud["criticos"], [])   # degrada, no bloquea
        finally:
            if original is not None:
                os.environ["MASTER_PASSWORD_HASH"] = original


if __name__ == "__main__":
    unittest.main()
