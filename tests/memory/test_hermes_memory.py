# -*- coding: utf-8 -*-
"""
tests/memory/test_hermes_memory.py — Memoria Hermes (Fase 25, ADR-0023).

CRITERIO DE EXITO: un agente 'recuerda' y aplica una solucion tecnica
discutida hace 3 dias — persistida en DB, sobreviviendo a un reinicio
(instancia NUEVA del store sobre el mismo archivo) — y la memoria esta
estrictamente aislada por usuario y por proyecto.

Aislamiento del entorno (leccion F22): APPDATA temporal + DB temporal +
singleton de Hermes re-apuntado en setUp y restaurado en tearDown.
"""
import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path

import core.vector_store as vs
from core import database as db
from core.embeddings import podar_fragmentos
from core.services.harness_service import ContextHarness, SkillHarness
from core.vector_store import VectorStoreHermes

HACE_3_DIAS = time.time() - 3 * 86400
SOLUCION = ("Para el error E-117 del PLC Modbus hay que recalibrar el registro "
            "40012 con escala 0.1 y reiniciar el adaptador con backoff")


def _corre(coro):
    return asyncio.run(coro)


class TestMemoriaHermes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._appdata_original = os.environ.get("APPDATA")
        cls._tmp = Path(tempfile.mkdtemp(prefix="agentdesk_hermes_"))
        os.environ["APPDATA"] = str(cls._tmp)          # skills/ y datos aislados
        db.init_db(db_path=cls._tmp / "hermes_test.db")  # auditoria aislada
        cls._ruta_store = cls._tmp / "memoria_vectorial.db"

    @classmethod
    def tearDownClass(cls):
        if cls._appdata_original is not None:
            os.environ["APPDATA"] = cls._appdata_original

    def setUp(self):
        # Singleton de Hermes re-apuntado al archivo aislado de la clase.
        vs._instancia = VectorStoreHermes(self._ruta_store)

    def tearDown(self):
        vs._instancia = None

    # ── Criterio de exito: recuerdo de hace 3 dias tras un reinicio ───────

    def test_01_recuerda_solucion_de_hace_3_dias_tras_reinicio(self):
        vs.hermes().guardar(
            SOLUCION, user_id="operador_a", proyecto_id="global",
            agente_id="ag_mantenimiento", ts=HACE_3_DIAS,
        )

        # 'Reinicio': instancia NUEVA sobre el MISMO archivo — si el
        # recuerdo aparece, la persistencia es real, no un cache en RAM.
        vs._instancia = VectorStoreHermes(self._ruta_store)

        harness = ContextHarness()
        harness.attach("ag_mantenimiento", {})
        contexto = _corre(harness.apply_hooks("pre", {
            "agente_id": "ag_mantenimiento",
            "mensaje": "el PLC Modbus vuelve a dar el error E-117, que hacemos?",
            "user_id": "operador_a",
        }))
        memoria = contexto.get("memoria_semantica", "")
        self.assertIn("E-117", memoria, "Debe recordar la solucion de hace 3 dias")
        self.assertIn("40012", memoria, "El detalle tecnico (registro) debe sobrevivir")
        self.assertIn("hace 3 dia", memoria, "El recuerdo debe declarar su antiguedad")

    # ── Aislamiento estricto ──────────────────────────────────────────────

    def test_02_otro_usuario_no_recibe_el_recuerdo(self):
        vs.hermes().guardar(SOLUCION, user_id="operador_a",
                            proyecto_id="global", ts=HACE_3_DIAS)
        harness = ContextHarness()
        harness.attach("ag_mantenimiento", {})
        contexto = _corre(harness.apply_hooks("pre", {
            "agente_id": "ag_mantenimiento",
            "mensaje": "el PLC Modbus vuelve a dar el error E-117, que hacemos?",
            "user_id": "operador_b",   # OTRO usuario
        }))
        self.assertNotIn("E-117", contexto.get("memoria_semantica", ""),
                         "La memoria de A jamas puede llegar a B (SEMANTIC-PRIVACY)")

    def test_03_otro_proyecto_no_recibe_el_recuerdo(self):
        vs.hermes().guardar(SOLUCION, user_id="operador_a",
                            proyecto_id="planta_norte", ts=HACE_3_DIAS)
        resultados = vs.hermes().buscar(
            "error E-117 del PLC Modbus",
            user_id="operador_a", proyecto_id="planta_sur",
        )
        self.assertEqual(resultados, [],
                         "Un proyecto no puede leer la memoria de otro")

    def test_04_scope_incompleto_es_fail_closed(self):
        with self.assertRaises(ValueError):
            vs.hermes().buscar("query", user_id="", proyecto_id="global")
        with self.assertRaises(ValueError):
            vs.hermes().buscar("query", user_id="operador_a", proyecto_id="")
        with self.assertRaises(ValueError):
            vs.hermes().guardar("texto", user_id="", proyecto_id="global")

    def test_05_sin_user_id_el_harness_no_consulta_nada(self):
        vs.hermes().guardar(SOLUCION, user_id="operador_a",
                            proyecto_id="global", ts=HACE_3_DIAS)
        harness = ContextHarness()
        harness.attach("ag_mantenimiento", {})
        contexto = _corre(harness.apply_hooks("pre", {
            "agente_id": "ag_mantenimiento",
            "mensaje": "error E-117",
            # sin user_id
        }))
        self.assertNotIn("memoria_semantica", contexto)

    # ── Poda de contexto dinamico (FinOps) ────────────────────────────────

    def test_06_poda_respeta_presupuesto_y_descarta_redundantes(self):
        base = "solucion al error E-117 recalibrar registro 40012 escala"
        fragmentos = [
            (f"- {base} (a)", 0.9),
            (f"- {base} (b)", 0.85),          # casi identico -> redundante
            ("- apunte distinto: la bomba 5 requiere purga semanal", 0.5),
            ("x" * 10_000, 0.4),              # no cabe en el presupuesto
        ]
        elegidos = podar_fragmentos(fragmentos, presupuesto_tokens=100)
        self.assertIn(fragmentos[0][0], elegidos)
        self.assertNotIn(fragmentos[1][0], elegidos, "El redundante debe podarse")
        self.assertTrue(all(len(e) <= 400 for e in elegidos))
        self.assertLessEqual(sum(len(e) for e in elegidos), 400,
                             "tokens ~= chars/4: 100 tokens = 400 chars maximo")

    # ── Habilidades: extraccion desde auditoria e inyeccion ───────────────

    def test_07_habilidad_extraida_de_auditoria_e_inyectada(self):
        from core.services import skill_service
        from core.services.audit_service import registrar_interaccion

        for _ in range(3):   # secuencia repetida y exitosa
            registrar_interaccion(
                tipo="tarea", agente_id="ag_reportes", user_id="operador_a",
                prompt="genera el reporte de curva S desde los datos Modbus",
                respuesta="reporte generado con exito",
                herramientas=["leer_modbus", "calcular_curva_s", "generar_pdf"],
                exitoso=True,
            )

        secuencias = skill_service.identificar_secuencias("operador_a")
        self.assertTrue(secuencias, "La secuencia repetida debe detectarse")
        self.assertEqual(secuencias[0]["secuencia"],
                         ["leer_modbus", "calcular_curva_s", "generar_pdf"])

        receta = skill_service.extraer_habilidad(
            "Generar Reporte de Curva S desde Modbus", "operador_a")
        self.assertEqual(receta["secuencia_herramientas"],
                         ["leer_modbus", "calcular_curva_s", "generar_pdf"])
        ruta = Path(os.environ["APPDATA"]) / "AgentDesk" / "skills" / f"{receta['slug']}.json"
        self.assertTrue(ruta.exists(), "La receta debe persistirse en skills/")

        harness = SkillHarness()
        harness.attach("ag_cualquiera", {})
        contexto = _corre(harness.apply_hooks("pre", {
            "agente_id": "ag_cualquiera",   # OTRO agente la puede invocar
            "mensaje": "necesito el reporte de curva S con datos del Modbus",
            "user_id": "operador_a",
        }))
        self.assertIn("Curva S", contexto.get("habilidades", ""),
                      "Otro agente del mismo usuario debe poder invocar la receta")

        # ...pero NUNCA un usuario distinto
        contexto_b = _corre(harness.apply_hooks("pre", {
            "agente_id": "ag_cualquiera",
            "mensaje": "necesito el reporte de curva S con datos del Modbus",
            "user_id": "operador_b",
        }))
        self.assertNotIn("Curva S", contexto_b.get("habilidades", ""))


if __name__ == "__main__":
    unittest.main()
