# -*- coding: utf-8 -*-
"""
tests/intent/test_intent_engine.py — Copiloto de Intencion (Fase 27, ADR-0025).

CRITERIO DE EXITO: ante una peticion en lenguaje natural, el orquestador
propone pasos que incluyen una Accion OT VALIDADA (filtro de limites
fisicos de la Fase 26) y una actualizacion del cronograma Gantt con
impacto en la Curva S — sin que el usuario escriba una linea de codigo.
Determinista: AGENTDESK_MODE=mock fuerza el planificador por reglas.
"""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import core.vector_store as vs
from core import database as db
from core.adapters.modbus_adapter import ModbusTelemetryAdapter
from core.services import intent_service
from core.services.ot_command_service import ot_service
from core.vector_store import VectorStoreHermes

OBJETIVO = ("Resetear la alarma E-117 de la linea tras el reporte de fallas "
            "y documentar el resultado")


def _sembrar_habilidad(tmp: Path, user_id: str, valor_ot: float = 1.0,
                       nombre: str = "Resetear alarma E-117") -> None:
    receta = {
        "slug": "resetear-alarma-e-117", "nombre": nombre,
        "descripcion": "Procedimiento validado para el error E-117",
        "secuencia_herramientas": ["leer_modbus", "proponer_comando_ot"],
        "comandos_ot": [{"adaptador": "modbus", "tag_id": "reset_alarma_e117",
                         "valor": valor_ot}],
        "ejemplo": {"prompt": "resetear la alarma E-117 de la linea", "respuesta": "ok",
                    "agente_id": "ag_mantenimiento"},
        "user_id": user_id, "creada": time.time(), "version": 1,
    }
    skills_dir = tmp / "AgentDesk" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / f"{receta['slug']}.json").write_text(
        json.dumps(receta, ensure_ascii=False), encoding="utf-8")
    vs.hermes().guardar(
        f"Habilidad: {nombre}. {receta['descripcion']}. "
        f"Herramientas: leer_modbus proponer_comando_ot. "
        f"Ejemplo: resetear la alarma E-117 de la linea",
        user_id=user_id, proyecto_id="global", tipo="habilidad",
    )


class TestCopilotoIntencion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._appdata_original = os.environ.get("APPDATA")
        cls._modo_original = os.environ.get("AGENTDESK_MODE")
        cls._tmp = Path(tempfile.mkdtemp(prefix="agentdesk_intent_"))
        os.environ["APPDATA"] = str(cls._tmp)
        os.environ["AGENTDESK_MODE"] = "mock"   # LLM determinista -> plan por reglas
        db.init_db(db_path=cls._tmp / "intent_test.db")

    @classmethod
    def tearDownClass(cls):
        if cls._appdata_original is not None:
            os.environ["APPDATA"] = cls._appdata_original
        if cls._modo_original is None:
            os.environ.pop("AGENTDESK_MODE", None)
        else:
            os.environ["AGENTDESK_MODE"] = cls._modo_original

    def setUp(self):
        vs._instancia = VectorStoreHermes(self._tmp / f"hermes_{time.time_ns()}.db")
        self.adaptador = ModbusTelemetryAdapter(host="")
        ot_service._adaptadores.clear()
        ot_service._propuestas.clear()
        ot_service.registrar_adaptador("modbus", self.adaptador)

    def tearDown(self):
        vs._instancia = None
        ot_service._adaptadores.clear()
        ot_service._propuestas.clear()

    def test_01_criterio_de_exito_lenguaje_natural_a_plan_completo(self):
        _sembrar_habilidad(self._tmp, "operador_a")

        plan = asyncio.run(intent_service.planificar(
            OBJETIVO, user_id="operador_a"))

        # Plan estructurado con pasos y la habilidad Hermes recuperada
        self.assertGreaterEqual(len(plan["pasos"]), 2)
        self.assertIn("Resetear alarma E-117", plan["habilidades"])

        # La Accion OT viene YA validada por el filtro de limites fisicos
        self.assertEqual(len(plan["acciones_ot"]), 1)
        accion = plan["acciones_ot"][0]
        self.assertEqual(accion["tag_id"], "reset_alarma_e117")
        self.assertEqual(plan["descartadas_por_filtro"], [])

        # Y tareas Gantt propuestas, una por paso
        self.assertEqual(len(plan["gantt_propuesto"]), len(plan["pasos"]))

        # Aplicar: cronograma real + impacto Curva S + OT a la bandeja HITL
        resultado = intent_service.aplicar_en_gantt(
            plan, "proj_copiloto", user_id="operador_a")
        self.assertEqual(len(resultado["tareas_creadas"]), len(plan["pasos"]))
        self.assertIn("antes", resultado["impacto_curva_s"])
        self.assertIn("despues", resultado["impacto_curva_s"])

        # Las tareas quedaron encadenadas Fin->Inicio en el Gantt real
        from core.gantt import motor_gantt
        proyecto = motor_gantt.obtener_proyecto("proj_copiloto")
        self.assertEqual(len(proyecto["tareas"]), len(plan["pasos"]))

        # La accion OT quedo PENDIENTE (Human-in-the-loop intacto):
        # cero escrituras sin aprobacion del operador
        pendientes = ot_service.listar("pendiente")
        self.assertEqual(len(pendientes), 1)
        self.assertEqual(self.adaptador.escrituras, [],
                         "El Copiloto jamas ejecuta: solo propone")

        # ...y el operador puede cerrarla con un clic (aprobacion real)
        r = ot_service.aprobar(pendientes[0]["id"], user_id="supervisor_1")
        self.assertTrue(r["ok"])
        self.assertEqual(len(self.adaptador.escrituras), 1)

    def test_02_accion_insegura_jamas_se_ofrece(self):
        _sembrar_habilidad(self._tmp, "operador_b", valor_ot=900.0,
                           nombre="Receta corrupta E-117")
        plan = asyncio.run(intent_service.planificar(
            "aplicar la receta corrupta E-117 de la linea", user_id="operador_b"))
        self.assertEqual(plan["acciones_ot"], [],
                         "Una accion fuera de limites JAMAS se muestra al usuario")
        self.assertEqual(len(plan["descartadas_por_filtro"]), 1)
        self.assertIn("limite fisico", plan["descartadas_por_filtro"][0]["motivo_descarte"])

    def test_03_scope_y_entradas_obligatorias(self):
        with self.assertRaises(ValueError):
            asyncio.run(intent_service.planificar("", user_id="operador_a"))
        with self.assertRaises(ValueError):
            asyncio.run(intent_service.planificar("objetivo", user_id=""))
        with self.assertRaises(ValueError):
            intent_service.aplicar_en_gantt({"gantt_propuesto": []}, "",
                                            user_id="operador_a")

    def test_04_sin_llm_el_plan_es_por_reglas_y_nunca_mudo(self):
        plan = asyncio.run(intent_service.planificar(
            "optimizar el consumo de la linea 4", user_id="operador_c"))
        self.assertEqual(plan["origen"], "reglas")
        self.assertGreaterEqual(len(plan["pasos"]), 2,
                                "Sin LLM el copiloto igual entrega un plan util")
        self.assertEqual(plan["acciones_ot"], [],
                         "Sin habilidad ni tag mencionado: cero acciones inventadas")

    def test_05_endpoints_exigen_supervisor(self):
        from fastapi.testclient import TestClient
        from core.api import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/copiloto/planificar", json={"objetivo": "x"})
        self.assertEqual(r.status_code, 403)
        r = c.post("/copiloto/aplicar", json={"plan": {}, "proyecto_id": "p"})
        self.assertEqual(r.status_code, 403)

    def test_06_plan_auditado_en_forense(self):
        from core.services.audit_service import consultar
        asyncio.run(intent_service.planificar(
            "revisar vibracion del motor 3", user_id="operador_d"))
        trazas = consultar(user_id="operador_d", limit=5)
        self.assertTrue(any(t["tipo"] == "copiloto_plan" for t in trazas))


if __name__ == "__main__":
    unittest.main()
