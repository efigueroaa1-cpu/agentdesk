# -*- coding: utf-8 -*-
"""
tests/persistence/test_dual_mode.py — Persistencia Dual + Alembic (Fase 15, ADR-0013).

Criterio de éxito: el sistema arranca correctamente tanto con SQLite (por
defecto, zero-config) como con PostgreSQL externo, y el esquema se crea/
actualiza automáticamente vía Alembic — no con un create_all() ciego.

No hay un servidor PostgreSQL real disponible en este entorno de
desarrollo (sin Docker, sin instancia local) — se prueba el camino
PostgreSQL con el fallo rápido y claro ante un servidor inalcanzable
(comportamiento real, no simulado) y con asyncpg mockeado para la ruta
exitosa. Usa bases SQLite temporales — no toca la DB real del usuario.
"""
import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import inspect, text

import core.database as db

_TABLAS_ESPERADAS = {
    "ejecuciones", "monitor_fuentes", "monitor_datos", "monitor_alertas",
    "usuarios", "guardrail_eventos", "gantt_tasks", "analisis_financiero",
    "refresh_tokens", "auditoria_ia",
}


class TestSQLiteViaAlembic(unittest.TestCase):
    """Camino zero-config: SQLite local, esquema gobernado por Alembic."""

    def test_01_arranque_crea_esquema_completo_via_alembic(self):
        tmp = Path(tempfile.mkdtemp()) / "fase15_sqlite.db"
        db.init_db(db_path=tmp)

        insp    = inspect(db._engine)
        tablas  = set(insp.get_table_names())
        self.assertIn("alembic_version", tablas,
                       "Alembic debe dejar su tabla de control, no create_all() puro")
        self.assertTrue(_TABLAS_ESPERADAS.issubset(tablas))

    def test_02_reinicio_es_idempotente(self):
        """Arrancar dos veces sobre el mismo archivo no falla ni duplica versiones."""
        tmp = Path(tempfile.mkdtemp()) / "fase15_reinicio.db"
        db.init_db(db_path=tmp)
        db.init_db(db_path=tmp)   # simula un reinicio de la app

        with db.get_session() as s:
            filas = s.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        self.assertEqual(len(filas), 1, "alembic_version debe tener exactamente una fila")

    def test_03_operaciones_crud_funcionan_tras_la_migracion(self):
        """El esquema creado por Alembic no es solo estructura: el ORM opera sobre él."""
        tmp = Path(tempfile.mkdtemp()) / "fase15_crud.db"
        db.init_db(db_path=tmp)

        db.guardar_ejecucion(
            agente_id="agente.demo", agente_nombre="Agente Demo",
            tarea="prueba fase 15", exitoso=True, duracion_s=0.5,
            resumen="ok", kpis={},
        )
        with db.get_session() as s:
            from core.database import Ejecucion
            fila = s.query(Ejecucion).filter_by(agente_id="agente.demo").first()
        self.assertIsNotNone(fila)
        self.assertEqual(fila.tarea, "prueba fase 15")


class TestMigracionesFallback(unittest.TestCase):
    """Si Alembic no está disponible, degrada a create_all() — nunca bloquea el arranque."""

    def test_04_alembic_config_roto_degrada_a_create_all(self):
        tmp = Path(tempfile.mkdtemp()) / "fase15_fallback.db"
        with patch("alembic.config.Config", side_effect=RuntimeError("config rota")):
            db.init_db(db_path=tmp)

        insp   = inspect(db._engine)
        tablas = set(insp.get_table_names())
        self.assertNotIn("alembic_version", tablas,
                          "El fallback usa create_all() puro, sin tabla de control")
        self.assertTrue(_TABLAS_ESPERADAS.issubset(tablas),
                         "Pese al fallo de Alembic, el esquema debe existir igual")


class TestPostgreSQLModoIndustrial(unittest.TestCase):
    """No hay servidor real disponible — se prueba el mecanismo, no una conexión viva."""

    def test_05_verificar_conexion_ignora_sqlite(self):
        # No debe intentar nada ni lanzar para URLs que no son postgres.
        db._verificar_conexion_async("sqlite:///no_aplica.db")

    def test_06_falla_rapido_y_claro_sin_servidor_real(self):
        """
        Comportamiento REAL (no mockeado): sin Postgres escuchando, el
        chequeo async debe fallar en segundos con un mensaje claro y las
        credenciales redactadas — nunca colgar el arranque.
        """
        url = "postgresql+psycopg2://usuario:clave_secreta@127.0.0.1:59999/no_existe"
        t0 = time.monotonic()
        with self.assertRaises(ConnectionError) as ctx:
            db._verificar_conexion_async(url)
        duracion = time.monotonic() - t0

        self.assertLess(duracion, 10.0, "El fallo debe ser rapido (timeout corto), no colgarse")
        mensaje = str(ctx.exception)
        self.assertNotIn("clave_secreta", mensaje, "Las credenciales NUNCA deben loggearse")
        self.assertIn("PostgreSQL", mensaje)

    def test_07_conexion_exitosa_mockeada_no_lanza(self):
        """Con asyncpg mockeado para simular un servidor sano, no debe lanzar."""
        conexion_falsa = AsyncMock()
        conexion_falsa.close = AsyncMock()

        with patch("asyncpg.connect", AsyncMock(return_value=conexion_falsa)):
            db._verificar_conexion_async(
                "postgresql+psycopg2://usuario:clave@10.0.0.5:5432/agentdesk_planta"
            )
        conexion_falsa.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
