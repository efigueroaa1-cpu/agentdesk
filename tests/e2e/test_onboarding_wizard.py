# -*- coding: utf-8 -*-
"""
tests/e2e/test_onboarding_wizard.py — Onboarding E2E (Fase 24, ADR-0022).

Criterio de exito: el flujo completo de PRIMER ARRANQUE en una maquina
limpia y OFFLINE TOTAL — sin .env, sin usuarios, sin licencia, sin red:

  1. El diagnostico enterprise detecta el estado (modo configuracion) sin
     ningun critico que impida arrancar (Zero-Default: ausencia es valida).
  2. El login sin configurar responde 503 con instrucciones ACCIONABLES
     (que agregar y donde), no un error criptico — erradica la UX hostil.
  3. El dashboard estatico (/ui/) y /health responden — el usuario VE la
     aplicacion, no una pantalla en blanco.
  4. El kill switch por licencia RSA local funciona sin red: sin licencia
     activo (modo libre), licencia simulada valida activa, adulterada o de
     otra maquina bloquea.

Aislamiento (leccion Fase 22): TODO el entorno se restaura en tearDown*;
APPDATA apunta a un tempdir (data_path() lo lee en cada llamada) y la DB
se re-apunta a un archivo temporal vacio (= tabla usuarios vacia = primer
arranque real).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from core import database as db
from core import kill_switch
from core.services import license_service

_ENV_AISLADAS = ("MASTER_PASSWORD_HASH", "AGENTDESK_JWT_SECRET",
                 "AGENTDESK_DB_URL", "AGENTDESK_LICENSE_FILE",
                 "AGENTDESK_LICENSE_PUB")


class TestOnboardingWizard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._env_original = {k: os.environ.get(k) for k in _ENV_AISLADAS}
        cls._appdata_original = os.environ.get("APPDATA")

        cls._tmp = Path(tempfile.mkdtemp(prefix="agentdesk_e2e_"))
        os.environ["APPDATA"] = str(cls._tmp)          # data_path() aislado
        for var in _ENV_AISLADAS:
            os.environ.pop(var, None)                  # primer arranque: sin .env
        os.environ["AGENTDESK_LICENSE_FILE"] = str(cls._tmp / "license.key")

        db.init_db(db_path=cls._tmp / "onboarding.db")  # tabla usuarios VACIA

        from core.api import app
        cls.client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env_original.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if cls._appdata_original is not None:
            os.environ["APPDATA"] = cls._appdata_original
        kill_switch.validar_ahora()   # estado del singleton coherente con el entorno restaurado

    def setUp(self):
        # Cada test parte sin licencia instalada y con el switch re-evaluado.
        Path(os.environ["AGENTDESK_LICENSE_FILE"]).unlink(missing_ok=True)
        os.environ.pop("AGENTDESK_LICENSE_PUB", None)
        kill_switch.validar_ahora()

    # ── Paso 1: deteccion de .env ausente via diagnostico enterprise ──────

    def test_01_diagnostico_detecta_modo_configuracion_sin_criticos(self):
        from core.services.boot_diagnostics_service import diagnostico_arranque_sistema
        salud = diagnostico_arranque_sistema(jwt_secret_path=self._tmp / "jwt_secret.key")
        self.assertEqual(salud["criticos"], [],
                         "Ausencia de secretos es valida (Zero-Default) — no debe impedir arrancar")
        self.assertTrue(salud["modo_configuracion"],
                        "Sin usuarios ni MASTER_PASSWORD_HASH debe reportar modo configuracion")

    # ── Paso 2: la UX del 503 inicial debe ser accionable ─────────────────

    def test_02_login_sin_configurar_responde_503_con_instrucciones(self):
        r = self.client.post("/auth/login",
                             json={"username": "admin", "password": "loquesea"})
        self.assertEqual(r.status_code, 503)
        detalle = r.json().get("detail", "")
        self.assertIn("MASTER_PASSWORD_HASH", detalle,
                      "El 503 debe decir QUE variable falta, no un error generico")
        self.assertIn(".env", detalle,
                      "El 503 debe decir DONDE configurarla")

    # ── Paso 3: acceso al dashboard (offline total) ───────────────────────

    def test_03_health_y_dashboard_responden(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

        r = self.client.get("/ui/")
        self.assertEqual(r.status_code, 200,
                         "El dashboard estatico debe servirse aun sin configurar")
        self.assertIn("<div id=\"root\"", r.text)

    # ── Paso 4: kill switch por licencia RSA local, sin red ───────────────

    def _emitir_licencia(self, machine_id: str, expira=None) -> str:
        """Par RSA efimero + licencia firmada; instala la publica via env."""
        priv, pub = license_service.generar_par_claves(bits=2048)  # efimera: 2048 acelera el test
        pub_path = self._tmp / "pub_efimera.pem"
        pub_path.write_text(pub, encoding="ascii")
        os.environ["AGENTDESK_LICENSE_PUB"] = str(pub_path)
        payload = {"machine_id": machine_id, "emitida": "2026-07-17",
                   "expira": expira, "edicion": "gold", "cliente": "E2E"}
        return json.dumps({"payload": payload,
                           "firma": license_service.firmar_payload(payload, priv)})

    def test_04_sin_licencia_modo_libre_activo(self):
        r = self.client.get("/kill-switch")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["active"], "Sin licencia el sistema arranca activo (modo libre)")
        self.assertEqual(data["fuente"], "default")
        self.assertFalse(data["licencia_presente"])
        self.assertTrue(data["machine_id"], "El endpoint debe exponer el ID de maquina para emitir licencias")

    def test_05_licencia_simulada_valida_activa_el_sistema(self):
        contenido = self._emitir_licencia(license_service.machine_id())
        veredicto = kill_switch.instalar_licencia(contenido)
        self.assertTrue(veredicto["valida"], veredicto["motivo"])
        self.assertTrue(kill_switch.is_active())
        estado = kill_switch.estado_dict()
        self.assertEqual(estado["fuente"], "licencia")
        self.assertEqual(estado["edicion"], "gold")

    def test_06_licencia_adulterada_bloquea(self):
        contenido = self._emitir_licencia(license_service.machine_id())
        doc = json.loads(contenido)
        doc["payload"]["edicion"] = "platinum"     # tamper post-firma
        adulterada = json.dumps(doc)

        veredicto = kill_switch.instalar_licencia(adulterada)
        self.assertFalse(veredicto["valida"])
        self.assertEqual(veredicto["motivo"], "firma_invalida")
        self.assertFalse(Path(os.environ["AGENTDESK_LICENSE_FILE"]).exists(),
                         "Una licencia invalida jamas debe persistirse")

        # Si el archivo adulterado aparece en disco (manipulacion directa),
        # la re-validacion del monitor bloquea los agentes.
        Path(os.environ["AGENTDESK_LICENSE_FILE"]).write_text(adulterada, encoding="utf-8")
        self.assertFalse(kill_switch.validar_ahora())
        self.assertEqual(kill_switch.estado_dict()["fuente"], "licencia_invalida")

    def test_07_licencia_de_otra_maquina_bloquea(self):
        contenido = self._emitir_licencia("0" * 32)
        Path(os.environ["AGENTDESK_LICENSE_FILE"]).write_text(contenido, encoding="utf-8")
        self.assertFalse(kill_switch.validar_ahora())
        self.assertEqual(kill_switch.estado_dict()["motivo"], "otra_maquina")

    def test_08_licencia_expirada_bloquea(self):
        contenido = self._emitir_licencia(license_service.machine_id(), expira="2020-01-01")
        Path(os.environ["AGENTDESK_LICENSE_FILE"]).write_text(contenido, encoding="utf-8")
        self.assertFalse(kill_switch.validar_ahora())
        self.assertEqual(kill_switch.estado_dict()["motivo"], "expirada")

    def test_09_endpoint_instalar_licencia_exige_admin(self):
        r = self.client.post("/kill-switch/licencia", json={"contenido": "{}"})
        self.assertEqual(r.status_code, 403,
                         "Instalar licencia sin token/rol admin debe rechazarse")


if __name__ == "__main__":
    unittest.main()
