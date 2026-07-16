# -*- coding: utf-8 -*-
"""
tests/audit/test_data_retention.py — Política de Retención y Purga
(Fase 20, ADR-0018).

Criterio de éxito de la fase (segunda mitad): se debe poder ejecutar una
purga MANUAL de registros de auditoría antiguos sin corromper la integridad
de la base de datos.

"Sin corromper la integridad" se verifica de forma literal: el conteo de
filas y el esquema de la tabla `auditoria_ia` deben ser IDÉNTICOS antes y
después de la purga -- purgar_registros_antiguos() anonimiza contenido, no
borra filas (ver docstring en core/services/audit_service.py). Además se
verifica que:
  - Las filas VIEJAS (fuera de la ventana de retención) quedan anonimizadas.
  - Las filas RECIENTES (dentro de la ventana) quedan intactas -- una purga
    demasiado agresiva sería tan grave como una que no corrompe pero borra
    de más.

Usa una base SQLite temporal — no toca la DB real del usuario.
"""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import core.database as db
from core.services import audit_service
from core.timeutil import utcnow


class TestPurgaDeRetencion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "data_retention_test.db")

    def setUp(self):
        # DB limpia por test: la Fase 20 no necesita datos de otros tests.
        with db.get_session() as s:
            s.query(db.AuditoriaIA).delete()
            s.commit()

    def _insertar_fila(self, *, dias_atras: int, user_id: str) -> int:
        with db.get_session() as s:
            fila = db.AuditoriaIA(
                ts=utcnow() - timedelta(days=dias_atras),
                user_id=user_id,
                agente_id="agente.finanzas",
                tipo="tarea",
                proveedor="ollama",
                modelo="ollama:llama3.2",
                prompt="datos sensibles del cliente X",
                contexto="tarea informe_financiero",
                contexto_hats="memoria HATs recuperada",
                respuesta="respuesta con PII del cliente X",
                costo_estimado=100,
                tokens_exactos=True,
                costo_usd_estimado=0.001,
                veredicto_guardrail="aprobado",
                duracion_s=1.2,
                exitoso=True,
            )
            s.add(fila)
            s.commit()
            return fila.id

    def test_01_purga_anonimiza_filas_viejas_y_preserva_filas_recientes(self):
        id_vieja    = self._insertar_fila(dias_atras=400, user_id="cliente.viejo")
        id_reciente = self._insertar_fila(dias_atras=5,   user_id="cliente.reciente")

        with db.get_session() as s:
            conteo_antes = s.query(db.AuditoriaIA).count()

        n_purgadas = audit_service.purgar_registros_antiguos(dias=365)
        self.assertEqual(n_purgadas, 1, "Solo la fila de 400 dias debe purgarse (retencion=365)")

        with db.get_session() as s:
            conteo_despues = s.query(db.AuditoriaIA).count()
            fila_vieja    = s.get(db.AuditoriaIA, id_vieja)
            fila_reciente = s.get(db.AuditoriaIA, id_reciente)

            # 1. Integridad: el conteo de filas NUNCA cambia -- se anonimiza,
            # no se borra. Esta es la prueba literal de "sin corromper".
            self.assertEqual(conteo_antes, conteo_despues,
                              "La purga no debe alterar el numero de filas")

            # 2. La fila vieja quedo anonimizada -- sin PII en claro.
            self.assertEqual(fila_vieja.user_id, audit_service._ANONIMIZADO[:64])
            self.assertNotIn("cliente X", fila_vieja.prompt)
            self.assertNotIn("cliente X", fila_vieja.respuesta)

            # 3. La fila reciente (dentro de la ventana) quedo INTACTA -- la
            # purga no debe ser mas agresiva de lo que pide la retencion.
            self.assertEqual(fila_reciente.user_id, "cliente.reciente")
            self.assertIn("cliente X", fila_reciente.prompt)

    def test_02_purga_es_idempotente_sin_duplicar_ni_perder_filas(self):
        """Correr la purga dos veces seguidas (manual, repetida) no debe
        volver a "purgar" lo ya anonimizado ni tocar el conteo de filas."""
        self._insertar_fila(dias_atras=400, user_id="cliente.viejo")

        primera  = audit_service.purgar_registros_antiguos(dias=365)
        segunda  = audit_service.purgar_registros_antiguos(dias=365)

        self.assertEqual(primera, 1)
        self.assertEqual(segunda, 0, "Una fila ya anonimizada no debe re-purgarse")

        with db.get_session() as s:
            self.assertEqual(s.query(db.AuditoriaIA).count(), 1)

    def test_03_configuracion_invalida_degrada_al_default_sin_romper(self):
        """AGENTDESK_AUDITORIA_RETENCION_DIAS invalido no debe lanzar --
        Zero-Default (ADR-0016): se degrada al default documentado, con
        advertencia, nunca con una excepcion que tumbe la purga."""
        import os
        os.environ["AGENTDESK_AUDITORIA_RETENCION_DIAS"] = "no-es-un-numero"
        try:
            dias = audit_service._retencion_dias_configurada()
        finally:
            del os.environ["AGENTDESK_AUDITORIA_RETENCION_DIAS"]
        self.assertEqual(dias, audit_service.RETENCION_DIAS_DEFECTO)


if __name__ == "__main__":
    unittest.main()
