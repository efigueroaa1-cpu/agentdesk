# -*- coding: utf-8 -*-
"""
tests/integration/test_cross_systems.py — Interacción cruzada de tres
subsistemas (Fase 17, ADR-0015): memoria HAT (ContextHarness, ADR-0009/0010),
delegación multi-agente (DelegationService, ADR-0011) y auditoría forense
(audit_service, ADR-0007/0014).

Motivación: cada subsistema tiene su propia suite (tests/harnesses/,
tests/collaboration/, tests/audit/) que lo valida AISLADO. Ninguna suite
anterior combina más de uno a la vez en el mismo flujo — el hueco que este
archivo cierra. Escenario: el Agente Finanzas delega una pregunta al Agente
Mantenimiento, que tiene el HAT de memoria activo y ya tiene un recuerdo
sembrado (de una sesión pasada, mismo user_id) relacionado con la pregunta.

Corre en AGENTDESK_MODE=mock — sin red, determinista. Usa una base SQLite
temporal — no toca la DB real del usuario.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["AGENTDESK_MODE"] = "mock"

import core.database as db
from core.services import audit_service
from core.services.delegation_service import DelegationService


class _OrqFake:
    """Orquestador mínimo: solo necesita exponer `.agentes` (dict id -> AgentBase)."""
    def __init__(self, agentes: dict):
        self.agentes = agentes


def _crear_agente(nombre: str, area: str, harnesses: list[str] | None = None):
    import core.orchestrator as orch

    class _ClienteFake:
        pass

    config = {
        "nombre": nombre, "tipo_ia": "chat", "modelo": "mock:agentdesk-demo",
        "area": area, "idioma": "espanol", "prompt_base": f"Eres {nombre}.",
        "harnesses": harnesses or [],
    }
    return orch.AgentBase(config, _ClienteFake(), "mock:agentdesk-demo")


class TestInteraccionCruzadaHATDelegacionAuditoria(unittest.IsolatedAsyncioTestCase):
    """
    Criterio de éxito (Fase 17): memoria HAT, delegación y auditoría forense
    siguen operando correctamente cuando actúan SIMULTÁNEAMENTE sobre la
    misma interacción, no solo cada una por separado.
    """

    @classmethod
    def setUpClass(cls):
        db.init_db(db_path=Path(tempfile.mkdtemp()) / "cross_systems_test.db")
        # Hecho sembrado en una sesión PASADA del agente destino, bajo el
        # MISMO user_id que hará la delegación más adelante — ContextHarness
        # (ADR-0010) filtra por user_id, no solo por agente_id.
        audit_service.registrar_interaccion(
            tipo="chat", agente_id="agente.mantenimiento",
            prompt="Cual es el torque recomendado para el motor XJ-200?",
            respuesta="El torque recomendado para el motor XJ-200 es de 45 Nm.",
            user_id="op.planta",
        )

    def setUp(self):
        self.agente_finanzas = _crear_agente("Agente Finanzas", "Finanzas")
        self.agente_mantenimiento = _crear_agente(
            "Agente Mantenimiento", "Mantenimiento", harnesses=["memoria"],
        )
        self.orq = _OrqFake({
            "agente.finanzas":       self.agente_finanzas,
            "agente.mantenimiento":  self.agente_mantenimiento,
        })
        self.svc = DelegationService(lambda: self.orq)

    @staticmethod
    def _espiar_prompts():
        """Intercepta core.providers.generate para capturar el prompt real enviado al LLM."""
        import core.providers as providers
        original = providers.generate
        capturados: list[str] = []

        async def _espia(model_id, prompt, temperature=0.4):
            capturados.append(prompt)
            return await original(model_id, prompt, temperature)

        return patch("core.providers.generate", side_effect=_espia), capturados

    async def test_01_delegacion_activa_memoria_hat_del_agente_destino(self):
        """
        Agente Finanzas delega en Agente Mantenimiento, que tiene el HAT de
        memoria activo. El torque sembrado en la sesión pasada del MISMO
        user_id debe llegar al prompt real que recibe el LLM durante la
        resolución delegada (chat_libre) — prueba que ContextHarness sigue
        operando dentro del flujo de delegación, no solo en chat directo
        (que es lo único que tests/harnesses/test_memoria_harness.py cubre).
        """
        parche, prompts = self._espiar_prompts()
        with parche:
            respuesta = await self.svc.speak(
                "agente.finanzas", "agente.mantenimiento",
                "recuerdame el torque del motor XJ-200", user_id="op.planta",
            )

        self.assertTrue(respuesta)
        self.assertTrue(prompts, "chat_libre no generó ninguna llamada al LLM")
        self.assertIn(
            "45 nm", prompts[0].lower(),
            "El HAT de memoria no inyectó el hecho sembrado en el prompt delegado "
            "— la memoria semántica no sobrevivió el paso por DelegationService",
        )

    async def test_02_ambos_lados_de_la_delegacion_quedan_auditados(self):
        """Mismo criterio que Fase 13 (tests/collaboration/test_delegation.py), reconfirmado con HAT activo."""
        await self.svc.speak(
            "agente.finanzas", "agente.mantenimiento",
            "torque del motor XJ-200", user_id="op.planta",
        )
        origen  = audit_service.consultar(agente_id="agente.finanzas", user_id="op.planta", limit=10)
        destino = audit_service.consultar(agente_id="agente.mantenimiento", user_id="op.planta", limit=10)

        delegado = [t for t in origen  if t.get("tipo") == "delegacion" and t.get("contexto") == "delegado"]
        resuelto = [t for t in destino if t.get("tipo") == "delegacion" and t.get("contexto") == "resuelto"]
        self.assertTrue(delegado, "Falta la traza del lado que delegó")
        self.assertTrue(resuelto, "Falta la traza del lado que resolvió")

    async def test_03_aislamiento_por_usuario_se_mantiene_dentro_de_la_delegacion(self):
        """
        ADR-0010 no se relaja por estar dentro de una delegación: un
        operador DISTINTO al que sembró el recuerdo no debe recibirlo,
        aunque delegue exactamente la misma pregunta al mismo agente.
        """
        parche, prompts = self._espiar_prompts()
        with parche:
            await self.svc.speak(
                "agente.finanzas", "agente.mantenimiento",
                "recuerdame el torque del motor XJ-200", user_id="op.planta.OTRO",
            )

        self.assertTrue(prompts)
        self.assertNotIn(
            "45 nm", prompts[0].lower(),
            "Un operador distinto al que sembró el dato NO debe recibirlo vía "
            "delegación (fail-closed, ADR-0010)",
        )

    async def test_04_contexto_hats_no_se_propaga_hoy_a_la_traza_de_delegacion(self):
        """
        Hallazgo real de esta fase (documentado, NO corregido aquí — fuera
        de alcance de Fase 17): DelegationService._auditar() (ADR-0011,
        Fase 13) no recibe ni pasa contexto_hats a
        audit_service.registrar_interaccion, a diferencia de
        OrchestratorService._auditar() (ADR-0014, Fase 16), que sí lo hace
        para chat/ejecutar_tarea directos.

        El HAT de memoria SÍ opera correctamente dentro de la delegación
        (test_01 lo prueba a nivel del prompt real que ve el LLM), pero ese
        contexto recuperado no queda capturado en la columna contexto_hats
        de auditoria_ia cuando la interacción llega vía delegación. Se dejó
        documentado en vez de silenciarlo, para que no se asuma cerrado
        solo porque ADR-0014 ya existe.
        """
        await self.svc.speak(
            "agente.finanzas", "agente.mantenimiento",
            "torque del motor XJ-200", user_id="op.planta",
        )
        destino  = audit_service.consultar(agente_id="agente.mantenimiento", user_id="op.planta", limit=10)
        resuelto = [t for t in destino if t.get("tipo") == "delegacion" and t.get("contexto") == "resuelto"]

        self.assertTrue(resuelto)
        self.assertEqual(
            resuelto[0].get("contexto_hats", ""), "",
            "Si este assert empieza a fallar es buena noticia: alguien cerró la "
            "brecha documentada en este test — actualizar el docstring y el ADR-0015.",
        )


if __name__ == "__main__":
    unittest.main()
