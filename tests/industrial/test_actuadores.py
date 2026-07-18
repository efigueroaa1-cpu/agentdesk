# -*- coding: utf-8 -*-
"""
tests/industrial/test_actuadores.py — Comando y Control de Bucle Cerrado
(Fase 26, ADR-0024).

CRITERIO DE EXITO end-to-end: un agente recupera de la Memoria Hermes el
recuerdo del error E-117 (sembrado hace 3 dias), PROPONE la accion
correctiva via la herramienta proponer_comando_ot, y SOLO tras la
aprobacion manual del operador (supervisor) el comando de escritura
Modbus simulado se ejecuta — y todo queda en la auditoria forense.
"""
import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path

import core.vector_store as vs
from core import database as db
from core.adapters.modbus_adapter import ModbusTelemetryAdapter
from core.services.harness_service import ContextHarness
from core.services.ot_command_service import OTCommandService, ot_service
from core.vector_store import VectorStoreHermes

HACE_3_DIAS = time.time() - 3 * 86400
RECUERDO_E117 = ("El error E-117 del PLC se resolvio reseteando la alarma: "
                 "escribir 1 en el tag reset_alarma_e117 tras verificar torque")


class TestBucleCerradoE117(unittest.TestCase):
    """El flujo completo del criterio de exito, paso a paso verificable."""

    @classmethod
    def setUpClass(cls):
        cls._appdata_original = os.environ.get("APPDATA")
        cls._tmp = Path(tempfile.mkdtemp(prefix="agentdesk_ot_"))
        os.environ["APPDATA"] = str(cls._tmp)
        db.init_db(db_path=cls._tmp / "ot_test.db")

    @classmethod
    def tearDownClass(cls):
        if cls._appdata_original is not None:
            os.environ["APPDATA"] = cls._appdata_original

    def setUp(self):
        vs._instancia = VectorStoreHermes(self._tmp / "memoria_vectorial.db")
        self.adaptador = ModbusTelemetryAdapter(host="")   # modo simulador
        # El tool del agente usa el singleton — se registra y limpia aqui.
        ot_service._adaptadores.clear()
        ot_service._propuestas.clear()
        ot_service.registrar_adaptador("modbus", self.adaptador)

    def tearDown(self):
        vs._instancia = None
        ot_service._adaptadores.clear()
        ot_service._propuestas.clear()

    def test_01_criterio_de_exito_e117_bucle_cerrado(self):
        from core.services.audit_service import consultar
        from core.tools import ejecutar_herramienta

        # 1) El recuerdo de hace 3 dias esta en Hermes (persistido en DB)
        vs.hermes().guardar(RECUERDO_E117, user_id="operador_a",
                            proyecto_id="global", agente_id="ag_mantenimiento",
                            ts=HACE_3_DIAS)

        # 2) El agente RECUERDA la solucion al consultar
        harness = ContextHarness()
        harness.attach("ag_mantenimiento", {})
        contexto = asyncio.run(harness.apply_hooks("pre", {
            "agente_id": "ag_mantenimiento",
            "mensaje": "aparecio de nuevo el error E-117 en el PLC, como lo corrijo?",
            "user_id": "operador_a",
        }))
        memoria = contexto.get("memoria_semantica", "")
        self.assertIn("E-117", memoria)
        self.assertIn("reset_alarma_e117", memoria,
                      "El recuerdo debe traer el tag correctivo")

        # 3) El agente PROPONE la accion (herramienta real del orquestador)
        salida = asyncio.run(ejecutar_herramienta(
            "proponer_comando_ot",
            {"adaptador": "modbus", "tag_id": "reset_alarma_e117", "valor": 1,
             "justificacion": "Recuerdo Hermes: E-117 se corrige reseteando la alarma"},
            agente_id_clave="ag_mantenimiento", user_id="operador_a",
        ))
        self.assertIn("Propuesta #", salida)
        self.assertIn("aprobacion", salida.lower())
        self.assertEqual(self.adaptador.escrituras, [],
                         "NADA debe escribirse antes de la aprobacion humana")

        # 4) Aprobacion manual del operador (el RBAC supervisor+ vive en el
        #    endpoint; aqui se ejerce el nucleo del servicio)
        pendientes = ot_service.listar("pendiente")
        self.assertEqual(len(pendientes), 1)
        resultado = ot_service.aprobar(pendientes[0]["id"], user_id="supervisor_1")
        self.assertTrue(resultado["ok"], resultado)

        # 5) La escritura Modbus simulada OCURRIO exactamente una vez
        self.assertEqual(len(self.adaptador.escrituras), 1)
        self.assertEqual(self.adaptador.escrituras[0]["tag_id"], "reset_alarma_e117")
        self.assertEqual(self.adaptador.escrituras[0]["valor"], 1.0)

        # 6) Auditoria forense completa: propuesta y comando ejecutado
        trazas = consultar(user_id="operador_a", limit=20)
        tipos = [t["tipo"] for t in trazas]
        self.assertIn("ot_propuesta", tipos)
        trazas_sup = consultar(user_id="supervisor_1", limit=20)
        comando = next(t for t in trazas_sup if t["tipo"] == "ot_comando")
        self.assertTrue(comando["exitoso"])
        self.assertIn("reset_alarma_e117", comando["prompt"])

    def test_02_fuera_de_limite_fisico_rechazado_en_origen(self):
        r = ot_service.proponer(adaptador="modbus", tag_id="setpoint_temp_reactor_2",
                                valor=900.0, justificacion="subir temperatura",
                                agente_id="ag_x", user_id="operador_a")
        self.assertFalse(r["ok"])
        self.assertIn("limite fisico", r["detalle"])
        self.assertEqual(ot_service.listar(), [],
                         "Una propuesta insegura ni siquiera entra a la bandeja")

    def test_03_escritura_directa_fuera_de_rango_imposible(self):
        r = self.adaptador.escribir_tag("setpoint_temp_reactor_2", 900.0)
        self.assertFalse(r["ok"])
        self.assertEqual(self.adaptador.escrituras, [])

    def test_04_tag_inexistente_rechazado(self):
        r = self.adaptador.escribir_tag("abrir_compuerta_inexistente", 1)
        self.assertFalse(r["ok"])
        self.assertIn("no existe", r["detalle"])

    def test_05_propuesta_expirada_no_se_ejecuta(self):
        ot_service.proponer(adaptador="modbus", tag_id="reset_alarma_e117",
                            valor=1, justificacion="reset", user_id="operador_a")
        p = ot_service.listar("pendiente")[0]
        ot_service._propuestas[p["id"]]["expira"] = time.time() - 1
        r = ot_service.aprobar(p["id"], user_id="supervisor_1")
        self.assertFalse(r["ok"])
        self.assertIn("expirada", r["detalle"])
        self.assertEqual(self.adaptador.escrituras, [])

    def test_06_endpoints_aprobacion_exigen_supervisor(self):
        from fastapi.testclient import TestClient
        from core.api import app
        c = TestClient(app, raise_server_exceptions=False)
        self.assertEqual(c.get("/ot/acciones").status_code, 403)
        self.assertEqual(c.post("/ot/acciones/1/aprobar").status_code, 403)
        self.assertEqual(c.post("/ot/acciones/1/rechazar").status_code, 403)

    def test_07_habilidad_accionable_referencia_hitl(self):
        from core.services import skill_service
        receta = {"nombre": "Resetear alarma E-117",
                  "secuencia_herramientas": ["leer_modbus", "proponer_comando_ot"],
                  "comandos_ot": [{"adaptador": "modbus",
                                   "tag_id": "reset_alarma_e117", "valor": 1.0}],
                  "ejemplo": {}}
        prompt = skill_service.como_prompt(receta)
        self.assertIn("proponer_comando_ot", prompt)
        self.assertIn("aprobacion del operador", prompt)

    def test_08_mqtt_tambien_valida_limites(self):
        from core.adapters.mqtt_adapter import MqttTelemetryAdapter
        ad = MqttTelemetryAdapter(broker="")
        ok = ad.escribir_tag("setpoint_horno_1", 200.0)
        self.assertTrue(ok["ok"])
        mal = ad.escribir_tag("setpoint_horno_1", 500.0)
        self.assertFalse(mal["ok"])
        self.assertEqual(len(ad.escrituras), 1)


class TestPurgaHermes(unittest.TestCase):
    """Deuda de ADR-0023 saldada: la retencion tambien purga a Hermes."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="agentdesk_purga_"))
        vs._instancia = VectorStoreHermes(self._tmp / "memoria_vectorial.db")

    def tearDown(self):
        vs._instancia = None

    def test_01_purga_elimina_viejos_y_preserva_recientes_y_habilidades(self):
        h = vs.hermes()
        h.guardar("recuerdo viejo de conversacion", user_id="u", proyecto_id="global",
                  ts=time.time() - 400 * 86400)
        h.guardar("recuerdo reciente", user_id="u", proyecto_id="global")
        h.guardar("Habilidad: receta antigua valiosa", user_id="u",
                  proyecto_id="global", tipo="habilidad",
                  ts=time.time() - 400 * 86400)

        eliminados = h.purgar_antiguos(365)
        self.assertEqual(eliminados, 1, "Solo la interaccion vieja se elimina")
        restantes = h.buscar("recuerdo reciente conversacion habilidad receta",
                             user_id="u", proyecto_id="global", top_k=10, umbral=0.0)
        textos = " | ".join(r["texto"] for r in restantes)
        self.assertNotIn("recuerdo viejo", textos)

        conteo = h.contar(user_id="u", proyecto_id="global")
        self.assertEqual(conteo, 2, "Reciente + habilidad sobreviven")

    def test_02_purga_es_idempotente_y_best_effort(self):
        h = vs.hermes()
        h.guardar("viejo", user_id="u", proyecto_id="global",
                  ts=time.time() - 400 * 86400)
        self.assertEqual(h.purgar_antiguos(365), 1)
        self.assertEqual(h.purgar_antiguos(365), 0, "Segunda pasada no re-purga")


if __name__ == "__main__":
    unittest.main()
