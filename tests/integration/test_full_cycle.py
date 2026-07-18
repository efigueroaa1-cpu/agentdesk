# -*- coding: utf-8 -*-
"""
tests/integration/test_full_cycle.py — Blitz de Integracion Real
(Fase 28, ADR-0026).

Validacion CRUZADA de los subsistemas a traves del TestClient de FastAPI
con JWT reales: Recuerdo Hermes -> Propuesta de Intencion -> Validacion
OT -> Recalculo Gantt P6 — mas la matriz RBAC completa, el ciclo de
habilidades, la licencia RSA y la superficie operativa (/health,
/metrics, /ui/). Cero mocks de servicios propios: DB real (temporal),
vector store real, MotorGantt real, filtro OT real; el unico doble es el
proveedor LLM (AGENTDESK_MODE=mock — un camino REAL del codigo, ADR-0016)
para que la suite sea determinista en CI.
"""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import core.vector_store as vs
from core import database as db
from core.adapters.modbus_adapter import ModbusTelemetryAdapter
from core.services.ot_command_service import ot_service
from core.vector_store import VectorStoreHermes

RECUERDO_E117 = ("El error E-117 del PLC se resolvio reseteando la alarma: "
                 "escribir 1 en el tag reset_alarma_e117 tras verificar torque")

_client = None


def _headers(rol: str, username: str | None = None) -> dict:
    from core.auth import crear_token
    token = crear_token(username or f"it_{rol}", rol)["token"]
    return {"Authorization": f"Bearer {token}"}


def setUpModule():
    """Entorno aislado UNA vez para todo el modulo (DB, APPDATA, Hermes, OT)."""
    global _client, _tmp, _appdata_original, _modo_original, _adaptador
    _appdata_original = os.environ.get("APPDATA")
    _modo_original = os.environ.get("AGENTDESK_MODE")
    _tmp = Path(tempfile.mkdtemp(prefix="agentdesk_fullcycle_"))
    os.environ["APPDATA"] = str(_tmp)
    os.environ["AGENTDESK_MODE"] = "mock"
    db.init_db(db_path=_tmp / "fullcycle.db")
    vs._instancia = VectorStoreHermes(_tmp / "memoria_vectorial.db")

    _adaptador = ModbusTelemetryAdapter(host="")
    ot_service._adaptadores.clear()
    ot_service._propuestas.clear()
    ot_service.registrar_adaptador("modbus", _adaptador)

    from core.api import app
    _client = TestClient(app, raise_server_exceptions=False)


def tearDownModule():
    if _appdata_original is not None:
        os.environ["APPDATA"] = _appdata_original
    if _modo_original is None:
        os.environ.pop("AGENTDESK_MODE", None)
    else:
        os.environ["AGENTDESK_MODE"] = _modo_original
    vs._instancia = None
    ot_service._adaptadores.clear()
    ot_service._propuestas.clear()


class Test01CicloCompletoHermesIntentOTGantt(unittest.TestCase):
    """El corazon del blitz: la cadena completa via HTTP con JWT real."""

    PROYECTO = "proy_fullcycle"
    plan = None

    @classmethod
    def setUpClass(cls):
        cls.sup = _headers("supervisor", "it_operador")
        vs.hermes().guardar(RECUERDO_E117, user_id="it_operador",
                            proyecto_id="global", agente_id="ag_mant",
                            ts=time.time() - 3 * 86400)
        # Habilidad aprendida (F25) con comando OT (F26): la fuente segura
        # de acciones del plan — el motor por reglas jamas inventa valores.
        receta = {
            "slug": "resetear-alarma-e-117", "nombre": "Resetear alarma E-117",
            "descripcion": "Procedimiento validado para el error E-117",
            "secuencia_herramientas": ["leer_modbus", "proponer_comando_ot"],
            "comandos_ot": [{"adaptador": "modbus",
                             "tag_id": "reset_alarma_e117", "valor": 1.0}],
            "ejemplo": {"prompt": "resetear la alarma E-117", "respuesta": "ok",
                        "agente_id": "ag_mant"},
            "user_id": "it_operador", "creada": time.time(), "version": 1,
        }
        skills_dir = _tmp / "AgentDesk" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "resetear-alarma-e-117.json").write_text(
            json.dumps(receta, ensure_ascii=False), encoding="utf-8")
        vs.hermes().guardar(
            "Habilidad: Resetear alarma E-117. Procedimiento validado para "
            "el error E-117. Herramientas: leer_modbus proponer_comando_ot. "
            "Ejemplo: resetear la alarma E-117",
            user_id="it_operador", proyecto_id="global", tipo="habilidad")

    def test_01_planificar_desde_lenguaje_natural(self):
        r = _client.post("/copiloto/planificar", headers=self.sup, json={
            "objetivo": "aparecio el error E-117: resetear la alarma "
                        "reset_alarma_e117 tras verificar el torque"})
        self.assertEqual(r.status_code, 200, r.text)
        type(self).plan = r.json()
        self.assertGreaterEqual(len(self.plan["pasos"]), 2)

    def test_02_memoria_hermes_alimento_el_plan(self):
        # El recuerdo de hace 3 dias esta accesible para el harness del agente
        from core.services.harness_service import ContextHarness
        h = ContextHarness()
        h.attach("ag_mant", {})
        ctx = asyncio.run(h.apply_hooks("pre", {
            "agente_id": "ag_mant", "mensaje": "error E-117 del PLC",
            "user_id": "it_operador"}))
        self.assertIn("E-117", ctx.get("memoria_semantica", ""))

    def test_03_acciones_ot_del_plan_vienen_validadas(self):
        acciones = self.plan["acciones_ot"]
        for a in acciones:
            ok, motivo = ot_service.validar(a["adaptador"], a["tag_id"], a["valor"])
            self.assertTrue(ok, motivo)

    def test_04_aplicar_crea_tareas_gantt_reales(self):
        r = _client.post("/copiloto/aplicar", headers=self.sup, json={
            "plan": self.plan, "proyecto_id": self.PROYECTO})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(len(data["tareas_creadas"]), len(self.plan["pasos"]))
        type(self).aplicado = data

    def test_05_gantt_recalculo_cpm_y_encadenamiento(self):
        from core.gantt import motor_gantt
        proyecto = motor_gantt.obtener_proyecto(self.PROYECTO)
        tareas = proyecto["tareas"]
        self.assertEqual(len(tareas), len(self.plan["pasos"]))
        # Encadenadas Fin->Inicio: cada tarea (salvo la 1a) depende de la previa
        ids = [t["id"] for t in tareas]
        for i, t in enumerate(tareas[1:], 1):
            self.assertEqual(t["dependencias"], [ids[i - 1]])

    def test_06_curva_s_refleja_el_cronograma_nuevo(self):
        r = _client.get(f"/analytics/curva-s/{self.PROYECTO}", headers=self.sup)
        self.assertEqual(r.status_code, 200)
        kpis = r.json().get("kpis", {})
        self.assertGreater(kpis.get("bac", 0), 0,
                           "El BAC debe existir tras insertar tareas")

    def test_07_accion_ot_quedo_pendiente_no_ejecutada(self):
        r = _client.get("/ot/acciones", headers=self.sup)
        self.assertEqual(r.status_code, 200)
        pendientes = [a for a in r.json()["acciones"] if a["estado"] == "pendiente"]
        self.assertGreaterEqual(len(pendientes), 1)
        self.assertEqual(_adaptador.escrituras, [],
                         "Cero escrituras antes de la aprobacion humana")
        type(self).pendiente_id = pendientes[0]["id"]

    def test_08_aprobacion_ejecuta_escritura_modbus_simulada(self):
        r = _client.post(f"/ot/acciones/{self.pendiente_id}/aprobar",
                         headers=_headers("supervisor", "it_supervisor"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(len(_adaptador.escrituras), 1)
        self.assertEqual(_adaptador.escrituras[0]["tag_id"], "reset_alarma_e117")

    def test_09_auditoria_forense_de_toda_la_cadena(self):
        r = _client.get("/auditoria/interacciones",
                        headers=self.sup, params={"limit": 50})
        self.assertEqual(r.status_code, 200)
        tipos = {t["tipo"] for t in r.json()["interacciones"]}
        self.assertIn("copiloto_plan", tipos)
        self.assertIn("ot_propuesta", tipos)
        self.assertIn("ot_comando", tipos)


class Test02MatrizRBAC(unittest.TestCase):
    """Cada superficie sensible rechaza al rol insuficiente."""

    def setUp(self):
        self.viewer = _headers("viewer")

    def test_01_copiloto_planificar_viewer_403(self):
        r = _client.post("/copiloto/planificar", headers=self.viewer,
                         json={"objetivo": "x"})
        self.assertEqual(r.status_code, 403)

    def test_02_copiloto_aplicar_viewer_403(self):
        r = _client.post("/copiloto/aplicar", headers=self.viewer,
                         json={"plan": {}, "proyecto_id": "p"})
        self.assertEqual(r.status_code, 403)

    def test_03_ot_bandeja_viewer_403(self):
        self.assertEqual(_client.get("/ot/acciones", headers=self.viewer).status_code, 403)

    def test_04_ot_aprobar_viewer_403(self):
        r = _client.post("/ot/acciones/999/aprobar", headers=self.viewer)
        self.assertEqual(r.status_code, 403)

    def test_05_skills_viewer_403(self):
        self.assertEqual(_client.get("/skills", headers=self.viewer).status_code, 403)

    def test_06_auditoria_viewer_403(self):
        r = _client.get("/auditoria/interacciones", headers=self.viewer)
        self.assertEqual(r.status_code, 403)

    def test_07_licencia_instalar_supervisor_403(self):
        # Instalar licencia exige ADMIN, ni siquiera supervisor
        r = _client.post("/kill-switch/licencia",
                         headers=_headers("supervisor"), json={"contenido": "{}"})
        self.assertEqual(r.status_code, 403)

    def test_08_token_forjado_no_eleva_privilegios(self):
        r = _client.get("/ot/acciones",
                        headers={"Authorization": "Bearer token.falso.xyz"})
        self.assertEqual(r.status_code, 403)


class Test03CicloHabilidades(unittest.TestCase):
    """Auditoria -> minado -> extraccion -> harness, todo via API + servicios."""

    @classmethod
    def setUpClass(cls):
        cls.sup = _headers("supervisor", "it_minero")
        from core.services.audit_service import registrar_interaccion
        for _ in range(3):
            registrar_interaccion(
                tipo="tarea", agente_id="ag_rep", user_id="it_minero",
                prompt="generar informe de vibracion del motor 3",
                respuesta="informe generado",
                herramientas=["leer_sensor", "generar_pdf"], exitoso=True)

    def test_01_secuencias_candidatas_visibles_en_api(self):
        r = _client.get("/skills", headers=self.sup)
        self.assertEqual(r.status_code, 200)
        secuencias = r.json()["secuencias_candidatas"]
        self.assertTrue(any(s["secuencia"] == ["leer_sensor", "generar_pdf"]
                            for s in secuencias))

    def test_02_extraer_habilidad_via_api(self):
        r = _client.post("/skills/extraer", headers=self.sup,
                         json={"nombre": "Informe de Vibracion Motor 3"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["habilidad"]["secuencia_herramientas"],
                         ["leer_sensor", "generar_pdf"])

    def test_03_habilidad_listada_solo_para_su_usuario(self):
        r = _client.get("/skills", headers=self.sup)
        nombres = [h["nombre"] for h in r.json()["habilidades"]]
        self.assertIn("Informe de Vibracion Motor 3", nombres)
        r2 = _client.get("/skills", headers=_headers("supervisor", "it_otro"))
        nombres2 = [h["nombre"] for h in r2.json()["habilidades"]]
        self.assertNotIn("Informe de Vibracion Motor 3", nombres2)

    def test_04_habilidad_alimenta_al_copiloto(self):
        r = _client.post("/copiloto/planificar", headers=self.sup, json={
            "objetivo": "necesito el informe de vibracion del motor 3"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Informe de Vibracion Motor 3", r.json()["habilidades"])

    def test_05_extraer_sin_secuencias_da_400_claro(self):
        r = _client.post("/skills/extraer",
                         headers=_headers("supervisor", "it_vacio"),
                         json={"nombre": "Nada"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("nada que extraer", r.json()["detail"].lower())


class Test04LicenciaYKillSwitch(unittest.TestCase):

    def test_01_estado_publico_expone_machine_id(self):
        r = _client.get("/kill-switch")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["active"])
        self.assertTrue(data["machine_id"])

    def test_02_licencia_corrupta_rechazada_400(self):
        r = _client.post("/kill-switch/licencia", headers=_headers("admin"),
                         json={"contenido": "{no es json"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("rechazada", r.json()["detail"].lower())

    def test_03_licencia_valida_activa_fuente_licencia(self):
        from core.services import license_service
        priv, pub = license_service.generar_par_claves(bits=2048)
        pub_path = _tmp / "pub_it.pem"
        pub_path.write_text(pub, encoding="ascii")
        os.environ["AGENTDESK_LICENSE_PUB"] = str(pub_path)
        os.environ["AGENTDESK_LICENSE_FILE"] = str(_tmp / "license_it.key")
        try:
            payload = {"machine_id": license_service.machine_id(),
                       "emitida": "2026-07-17", "expira": None,
                       "edicion": "it", "cliente": "blitz"}
            contenido = json.dumps({
                "payload": payload,
                "firma": license_service.firmar_payload(payload, priv)})
            r = _client.post("/kill-switch/licencia", headers=_headers("admin"),
                             json={"contenido": contenido})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["fuente"], "licencia")
        finally:
            os.environ.pop("AGENTDESK_LICENSE_PUB", None)
            os.environ.pop("AGENTDESK_LICENSE_FILE", None)
            from core import kill_switch
            kill_switch.validar_ahora()

    def test_04_toggle_manual_bloquea_y_reactiva(self):
        adm = _headers("admin")
        r = _client.post("/kill-switch/toggle", headers=adm, json={"activo": False})
        self.assertFalse(r.json()["active"])
        r = _client.post("/kill-switch/toggle", headers=adm, json={"activo": True})
        self.assertTrue(r.json()["active"])


class Test05SuperficieOperativa(unittest.TestCase):

    def test_01_health_ok(self):
        r = _client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_02_metrics_prometheus_expone_series(self):
        r = _client.get("/metrics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("agentdesk_", r.text)

    def test_03_diagnostico_llm_publico(self):
        r = _client.get("/diagnostico/llm")
        self.assertEqual(r.status_code, 200)

    def test_04_dashboard_estatico_servido(self):
        r = _client.get("/ui/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<div id=\"root\"", r.text)

    def test_05_diagnostico_arranque_supervisor(self):
        r = _client.get("/diagnostico/arranque", headers=_headers("supervisor"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("modo_configuracion", r.json())


if __name__ == "__main__":
    unittest.main()
