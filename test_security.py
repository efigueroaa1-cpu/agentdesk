"""
Suite unittest de seguridad para los endpoints de backup (RBAC + JWT).

Valida que el endpoint de restauración de backups sea inexpugnable:
  - admin con JWT válido    → PUEDE restaurar (200, restaurar_backup se ejecuta).
  - viewer / supervisor     → 403 Forbidden, restaurar_backup NUNCA se ejecuta.
  - sin token / token basura→ 403 Forbidden (deny-by-default como anónimo).
  - todo rechazo queda en el log de auditoría con user_id e IP.

Ejecutar con:  python -m unittest test_security -v
"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.api import app
from core.auth import crear_token

# TestClient sin context manager: no dispara los eventos de startup
# (no necesitamos orquestador ni WebSockets para probar el RBAC HTTP).
client = TestClient(app)

ZIP_FALSO = {"archivo": ("backup.zip", b"PK\x03\x04contenido-de-prueba", "application/zip")}


def _headers(rol: str) -> dict:
    """Genera un JWT real firmado con la clave del sistema para el rol dado."""
    token = crear_token(f"test_{rol}", rol)["token"]
    return {"Authorization": f"Bearer {token}"}


class TestBackupRestaurarRBAC(unittest.TestCase):

    # ── Caso autorizado ────────────────────────────────────────────────────────

    def test_01_admin_puede_restaurar(self):
        """Un admin con JWT válido restaura sin problema (restaurar_backup se ejecuta)."""
        with patch("core.backup.restaurar_backup",
                   return_value={"ok": True, "total": 7}) as mock_restore:
            r = client.post("/backup/restaurar", headers=_headers("admin"), files=ZIP_FALSO)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["total"], 7)
        mock_restore.assert_called_once()

    # ── Casos rechazados ───────────────────────────────────────────────────────

    def _assert_rechazado(self, headers: dict | None):
        """Helper: la petición debe dar 403 y restaurar_backup NO debe ejecutarse."""
        with patch("core.backup.restaurar_backup") as mock_restore:
            r = client.post("/backup/restaurar", headers=headers or {}, files=ZIP_FALSO)
        self.assertEqual(r.status_code, 403, f"Esperaba 403, llegó {r.status_code}: {r.text}")
        self.assertIn("admin", r.json()["detail"])
        mock_restore.assert_not_called()

    def test_02_viewer_rechazado_403(self):
        """Un viewer autenticado recibe 403 Forbidden."""
        self._assert_rechazado(_headers("viewer"))

    def test_03_supervisor_rechazado_403(self):
        """Un supervisor autenticado recibe 403 Forbidden (solo admin restaura)."""
        self._assert_rechazado(_headers("supervisor"))

    def test_04_sin_token_rechazado_403(self):
        """Sin Authorization header se trata como anónimo/viewer → 403."""
        self._assert_rechazado(None)

    def test_05_token_invalido_rechazado_403(self):
        """Un token corrupto/forjado no eleva privilegios → 403."""
        self._assert_rechazado({"Authorization": "Bearer token.falso.manipulado"})

    # ── Auditoría ─────────────────────────────────────────────────────────────

    def test_06_rechazo_deja_log_de_auditoria_con_user_e_ip(self):
        """El intento denegado queda registrado con user_id, rol e IP."""
        with patch("core.backup.restaurar_backup") as mock_restore, \
             self.assertLogs("core.api", level="WARNING") as cm:
            r = client.post("/backup/restaurar", headers=_headers("viewer"), files=ZIP_FALSO)
        self.assertEqual(r.status_code, 403)
        mock_restore.assert_not_called()
        log = "\n".join(cm.output)
        self.assertIn("AUDITORIA_SEGURIDAD", log)
        self.assertIn("DENEGADA", log)
        self.assertIn("user_id=test_viewer", log)
        self.assertIn("rol=viewer", log)
        self.assertIn("ip=", log)

    def test_07_autorizacion_admin_tambien_queda_auditada(self):
        """La restauración autorizada también deja rastro con user_id e IP."""
        with patch("core.backup.restaurar_backup",
                   return_value={"ok": True, "total": 1}), \
             self.assertLogs("core.api", level="INFO") as cm:
            r = client.post("/backup/restaurar", headers=_headers("admin"), files=ZIP_FALSO)
        self.assertEqual(r.status_code, 200)
        log = "\n".join(cm.output)
        self.assertIn("AUTORIZADA", log)
        self.assertIn("user_id=test_admin", log)


class TestBackupDescargarRBAC(unittest.TestCase):
    """GET /backup/descargar sigue el mismo estándar: solo admin + auditoría."""

    def test_01_admin_puede_descargar(self):
        """Un admin descarga el ZIP y la operación queda auditada."""
        with patch("core.backup.crear_backup", return_value=b"PK\x03\x04zip-falso"), \
             self.assertLogs("core.api", level="INFO") as cm:
            r = client.get("/backup/descargar", headers=_headers("admin"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/zip")
        log = "\n".join(cm.output)
        self.assertIn("descarga de backup AUTORIZADA", log)
        self.assertIn("user_id=test_admin", log)

    def test_02_no_admin_rechazado_con_auditoria(self):
        """viewer, supervisor y anónimo reciben 403 y quedan en el log de auditoría."""
        for headers, user_esperado in [
            (_headers("viewer"), "test_viewer"),
            (_headers("supervisor"), "test_supervisor"),
            (None, "anonimo"),
        ]:
            with self.subTest(user=user_esperado), \
                 patch("core.backup.crear_backup") as mock_backup, \
                 self.assertLogs("core.api", level="WARNING") as cm:
                r = client.get("/backup/descargar", headers=headers or {})
            self.assertEqual(r.status_code, 403)
            mock_backup.assert_not_called()
            log = "\n".join(cm.output)
            self.assertIn("descarga de backup DENEGADA", log)
            self.assertIn(f"user_id={user_esperado}", log)
            self.assertIn("ip=", log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
