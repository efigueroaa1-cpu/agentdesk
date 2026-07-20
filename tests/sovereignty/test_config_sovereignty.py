# -*- coding: utf-8 -*-
"""
tests/sovereignty/test_config_sovereignty.py — config.json fuera del binario
(2026-07-20).

Hasta ahora config.json se leia (y orchestrator.py lo ESCRIBIA) siempre en
resource_path() — dentro de _internal/ en el build empaquetado. restaurar_backup()
ya escribia el config.json restaurado en %APPDATA%\\AgentDesk (data_path), pero
nada volvia a leerlo de ahi: una restauracion de backup dejaba un archivo muerto,
invisible en runtime. Ademas, cualquier reinstalacion/actualizacion del .exe podia
pisar los agentes/prompts personalizados del usuario.

Fix: config_path() (path_manager) resuelve la copia ESCRIBIBLE en %APPDATA%,
bootstrapeada UNA vez desde la plantilla de solo lectura empaquetada — mismo
patron que .env/env.example en config_api.py.

Aislamiento: APPDATA se redirige a un directorio temporal por test (misma
tecnica que la prueba de humo de Fase 10/11) — nunca se toca el perfil real.

Correr: python -m unittest tests.sovereignty.test_config_sovereignty -v
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


class TestConfigPathSoberania(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="agentdesk_sov_")
        self._appdata_previo = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp

    def tearDown(self):
        if self._appdata_previo is not None:
            os.environ["APPDATA"] = self._appdata_previo
        else:
            os.environ.pop("APPDATA", None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_01_bootstrapea_desde_la_plantilla_si_no_existe_en_appdata(self):
        from core.path_manager import config_path
        destino = config_path()
        self.assertTrue(destino.exists(), "debe copiar la plantilla al primer llamado")
        self.assertTrue(str(destino).startswith(self._tmp),
                        "la copia escribible debe vivir en %APPDATA%, no en el bundle")
        data = json.loads(destino.read_text(encoding="utf-8"))
        self.assertIn("agents", data)

    def test_02_no_pisa_una_copia_de_usuario_ya_existente(self):
        from core.path_manager import config_path, data_path
        # Simula un usuario que ya edito su config.json en APPDATA.
        propio = data_path("config.json")
        propio.write_text(json.dumps({"agents": [], "marca_usuario": True}), encoding="utf-8")

        destino = config_path()
        data = json.loads(destino.read_text(encoding="utf-8"))
        self.assertTrue(data.get("marca_usuario"),
                        "una copia de usuario existente jamas debe ser sobreescrita")

    def test_03_load_config_sin_ruta_explicita_usa_la_copia_escribible(self):
        from core.config_loader import load_config
        from core.path_manager import config_path
        cfg = load_config()
        self.assertIn("agents", cfg)
        self.assertTrue(config_path().exists())

    def test_04_restaurar_backup_deja_un_config_json_que_load_config_si_lee(self):
        """Criterio de exito: el config.json restaurado por un backup deja de
        ser un archivo muerto — load_config() debe verlo de inmediato."""
        from core.backup import restaurar_backup
        from core.config_loader import load_config
        import io
        import zipfile

        buf = io.BytesIO()
        contenido = {"agents": [{"id": "agente_restaurado", "nombre": "Restaurado",
                                 "tipo_ia": "analitico", "area": "Test",
                                 "modelo": "mock:agentdesk-demo", "temperatura": 0.2,
                                 "idioma": "espanol", "prompt_base": "x",
                                 "siguiente_agente_id": None}]}
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("backup_info.json", json.dumps({"version": "test", "ts": "hoy"}))
            zf.writestr("config.json", json.dumps(contenido))

        resultado = restaurar_backup(buf.getvalue())
        self.assertTrue(resultado["ok"])
        self.assertIn("config.json", resultado["restaurados"])

        cfg = load_config()
        self.assertEqual([a["id"] for a in cfg["agents"]], ["agente_restaurado"],
                         "load_config() debe leer EXACTAMENTE lo que restauro el backup")


if __name__ == "__main__":
    unittest.main()
