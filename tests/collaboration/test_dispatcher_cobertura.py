# -*- coding: utf-8 -*-
"""
tests/collaboration/test_dispatcher_cobertura.py — Cobertura del dispatcher
de herramientas (2026-07-26).

Regresion real: durante el Strangler Fig de tools.py (incremento 3) la linea
`from core.tools_finance import _calcular_financiero` se arrastro por error a
tools_chile.py y el dispatcher quedo llamando a un nombre no importado ->
la tool calcular_financiero fallaba con NameError. NINGUN test la ejercitaba
via ejecutar_herramienta, asi que el gate no lo vio.

Este test cierra el hueco: TODA tool declarada en TOOLS_SCHEMA debe ser
resoluble por el dispatcher -- ni 'no reconocida' ni 'is not defined'
(NameError por import faltante). No valida la logica de cada tool (eso es de
sus tests), solo que el cableado nombre->funcion este intacto.

Correr:  python -m unittest tests.collaboration.test_dispatcher_cobertura -v
"""
import asyncio
import unittest

from core.tools import TOOLS_SCHEMA, ejecutar_herramienta, factory


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=20))


# Tools SIN dependencia de red: se pueden ejecutar de verdad en el test para
# cazar un NameError en el lambda del factory. Las de red se cubren por
# registro + por el import a nivel de modulo (ver test_01).
_TOOLS_LOCALES = {
    "calcular":            {"expresion": "1+1"},
    "calcular_financiero": {"tipo": "van_tir",
                            "datos": {"flujos": [-100, 50, 80], "tasa_descuento": 0.1}},
    "listar_archivos":     {},
    "leer_archivo":        {},
}


class TestDispatcherCobertura(unittest.TestCase):

    def _nombres_schema(self):
        nombres = []
        for t in TOOLS_SCHEMA:
            fn = t.get("function", t)
            if "name" in fn:
                nombres.append(fn["name"])
        return nombres

    def test_01_toda_tool_del_schema_esta_registrada(self):
        """Cada tool del schema tiene un adaptador en el factory (cableado
        completo). Determinista y SIN red: una tool declarada pero no
        registrada haria 'no reconocida' en produccion.

        Las funciones que los lambdas referencian son imports a nivel de modulo
        de core/tools/__init__.py -> una funcion faltante ROMPE el import (se
        caza al cargar). El bug de calcular_financiero (2026-07-26) se escapo
        porque la LINEA de import faltaba entera y ninguna tool local lo llamaba;
        ahora test_02 lo ejecuta de verdad."""
        no_registradas = [n for n in self._nombres_schema() if factory.resolver(n) is None]
        self.assertEqual(no_registradas, [], f"tools sin adaptador en el factory: {no_registradas}")

    def test_01b_tools_locales_se_ejecutan_sin_nameerror(self):
        """Ejecucion REAL de las tools sin red: caza un NameError en el lambda
        del factory (funcion referenciada pero no importada)."""
        fallos = []
        for nombre, args in _TOOLS_LOCALES.items():
            r = _run(ejecutar_herramienta(nombre, args))
            if "no reconocida" in r or "is not defined" in r:
                fallos.append(f"{nombre}: {r[:80]}")
        self.assertEqual(fallos, [], f"tools locales mal cableadas: {fallos}")

    def test_02_calcular_financiero_cableada(self):
        """Regresion puntual: la tool que se rompio en el incremento 3."""
        r = _run(ejecutar_herramienta(
            "calcular_financiero",
            {"tipo": "van_tir", "datos": {"flujos": [-1000, 300, 400, 500], "tasa_descuento": 0.1}},
        ))
        self.assertNotIn("is not defined", r)
        self.assertNotIn("no reconocida", r)

    def test_03_calcular_cableada_y_correcta(self):
        r = _run(ejecutar_herramienta("calcular", {"expresion": "2 + 3 * 4"}))
        self.assertIn("14", r)


if __name__ == "__main__":
    unittest.main()
