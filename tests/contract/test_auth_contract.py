# -*- coding: utf-8 -*-
"""
tests/contract/test_auth_contract.py — Test-Contrato de Seguridad Crítica.

Invariante: NADIE puede añadir un endpoint de escritura (POST/PUT/DELETE/PATCH)
sin protección JWT por accidente. Cada ruta de escritura debe estar:
  a) protegida por el JWTMiddleware (métodos protegidos o rutas siempre
     protegidas de core/api/auth_router.py), o
  b) declarada EXPLÍCITAMENTE en RUTAS_PUBLICAS_AUTORIZADAS con su justificación.

Si alguien agrega una ruta de escritura nueva y no la clasifica aquí de forma
consciente, este test falla y el Gate bloquea el commit.

Correr:  python -m unittest tests.contract.test_auth_contract -v
"""
import unittest

from fastapi.testclient import TestClient

from core.api import app
from core.api.auth_router import _METODOS_PROTEGIDOS, _RUTAS_SIEMPRE_PROTEGIDAS

METODOS_ESCRITURA = {"POST", "PUT", "DELETE", "PATCH"}

# Rutas de escritura autorizadas a pasar el middleware SIN token.
# Ojo: "sin token en el middleware" no significa "sin seguridad" — varias
# verifican RBAC dentro del handler (request.state.rol, deny-by-default viewer).
# Añadir una entrada aquí es una decisión de seguridad consciente y revisable.
RUTAS_PUBLICAS_AUTORIZADAS: frozenset[tuple[str, str]] = frozenset({
    # Autenticación (el login ES la puerta; el CRUD exige rol admin en handler)
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),   # canje de refresh token: el token ES la credencial
    ("POST", "/auth/usuarios"),
    ("PUT",  "/auth/usuarios/{username}/rol"),
    ("PUT",  "/auth/usuarios/{username}/activo"),
    # Backup: RBAC admin + auditoría AUDITORIA_SEGURIDAD dentro del handler
    ("POST", "/backup/restaurar"),
    # Operación de agentes (interfaz principal de la app de escritorio local)
    ("POST", "/agentes"),
    ("PUT",  "/agentes/{agente_id}"),
    ("POST", "/agentes/{agente_id}/ejecutar"),
    ("POST", "/agentes/ejecutar-todos"),
    ("POST", "/reload"),
    # Chat / análisis / reportes
    ("POST", "/chat"),
    ("POST", "/chat/stream"),
    ("POST", "/upload"),
    ("POST", "/generar-pdf"),
    # Motores de dominio (Gantt, finanzas, scheduler, pipeline, alertas)
    ("POST",  "/gantt/{proyecto_id}/tareas"),
    ("PUT",   "/gantt/tareas/{tarea_id}"),
    ("PATCH", "/gantt/tareas/{tarea_id}/progreso"),
    ("POST",  "/finanzas/analizar"),
    ("POST",  "/finanzas/reload/{agente_id}"),
    ("PUT",   "/scheduler/tareas/{tarea_id}"),
    ("POST",  "/scheduler/tareas/{tarea_id}/ejecutar"),
    ("PUT",   "/pipeline/config"),
    ("PUT",   "/alertas/config"),
    # Infraestructura local
    ("POST", "/kill-switch/toggle"),
    ("POST", "/kill-switch/url"),
    ("PUT",  "/update/url"),
    # Map-Reduce (Fase 21, ADR-0019): RBAC supervisor+ dentro del handler
    # (dispara N llamadas reales a LLM, mismo criterio que /auditoria/*)
    ("POST", "/orquestador/mapreduce"),
    # Webhook externo: autenticación propia por bcrypt en el handler
    ("POST", "/webhook/whatsapp"),
})


def rutas_de_escritura() -> set[tuple[str, str]]:
    """Recorre TODAS las rutas de la app (incluye routers anidados)."""
    encontradas: set[tuple[str, str]] = set()

    def _recorrer(router):
        for r in getattr(router, "routes", []):
            metodos = getattr(r, "methods", None)
            path    = getattr(r, "path", None)
            if metodos and path:
                for m in metodos & METODOS_ESCRITURA:
                    encontradas.add((m, path))
            elif getattr(r, "original_router", None) is not None:
                _recorrer(r.original_router)   # fastapi._IncludedRouter
            elif getattr(r, "routes", None):
                _recorrer(r)                   # Mount / sub-router genérico

    _recorrer(app.router)
    return encontradas


def protegida_por_middleware(metodo: str, path: str) -> bool:
    """Replica la política del JWTMiddleware: cuándo se EXIGE token."""
    return metodo in _METODOS_PROTEGIDOS or path in _RUTAS_SIEMPRE_PROTEGIDAS


class TestContratoEscrituraJWT(unittest.TestCase):
    """Toda escritura está protegida por JWT o autorizada explícitamente."""

    def test_01_ninguna_escritura_sin_clasificar(self):
        """Falla si aparece un endpoint de escritura no protegido ni autorizado."""
        sin_clasificar = sorted(
            (m, p) for (m, p) in rutas_de_escritura()
            if not protegida_por_middleware(m, p)
            and (m, p) not in RUTAS_PUBLICAS_AUTORIZADAS
        )
        self.assertEqual(
            sin_clasificar, [],
            "\n\nENDPOINTS DE ESCRITURA SIN PROTECCION JWT NI AUTORIZACION EXPLICITA:\n  "
            + "\n  ".join(f"{m} {p}" for m, p in sin_clasificar)
            + "\n\nProtejelos via JWTMiddleware o, si su exposicion es una decision "
              "consciente, agregalos a RUTAS_PUBLICAS_AUTORIZADAS con justificacion.",
        )

    def test_02_lista_blanca_sin_entradas_muertas(self):
        """Falla si la lista blanca autoriza rutas que ya no existen (higiene)."""
        existentes = rutas_de_escritura()
        muertas = sorted(RUTAS_PUBLICAS_AUTORIZADAS - existentes)
        self.assertEqual(
            muertas, [],
            "\n\nEntradas de la lista blanca que ya no existen en la API "
            "(eliminalas):\n  " + "\n  ".join(f"{m} {p}" for m, p in muertas),
        )

    def test_03_delete_sin_token_rechazado_401(self):
        """El middleware exige token en TODO DELETE (verificación en vivo)."""
        # Sin `with`: no disparar el lifespan/startup (mismo patrón que test_security)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.delete("/agentes/agente_inexistente")
        self.assertEqual(r.status_code, 401)

    def test_04_rutas_siempre_protegidas_sin_token_401(self):
        """Las rutas siempre protegidas rechazan peticiones sin token (en vivo)."""
        c = TestClient(app, raise_server_exceptions=False)
        for ruta in sorted(_RUTAS_SIEMPRE_PROTEGIDAS):
            with self.subTest(ruta=ruta):
                metodo = "POST" if ruta == "/auth/cambiar-password" else "PUT"
                r = c.request(metodo, ruta, json={})
                self.assertEqual(r.status_code, 401, f"{metodo} {ruta}")


if __name__ == "__main__":
    unittest.main()
