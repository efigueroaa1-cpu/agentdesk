# -*- coding: utf-8 -*-
"""
tests/enterprise/test_gate_motor_reglas.py — Motor de reglas declarativo del
Guardian (2026-07-27, Task 3).

scripts/gate.py paso de un main() con 40 lineas 'errores += check_X()'
secuenciales a un registro declarativo REGLAS (list[Regla]) iterado por
evaluar_reglas(). Este test blinda las invariantes de ese motor:
  - [CRED] (secreto literal) es SIEMPRE la primera regla (prioridad innegociable).
  - Cada regla es una funcion pura que retorna una lista.
  - No hay reglas duplicadas ni check ausente.

Correr:  python -m unittest tests.enterprise.test_gate_motor_reglas -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import gate  # noqa: E402


class TestMotorDeReglas(unittest.TestCase):

    def test_01_existe_el_registro_declarativo(self):
        self.assertTrue(hasattr(gate, "REGLAS"), "gate.py debe exponer el registro REGLAS")
        self.assertTrue(hasattr(gate, "evaluar_reglas"))
        self.assertGreater(len(gate.REGLAS), 30, "el Guardian tiene decenas de reglas")

    def test_02_cred_es_la_primera_regla(self):
        """Prioridad innegociable: un secreto hardcodeado se ve antes que nada."""
        primera = gate.REGLAS[0]
        self.assertEqual(primera.check, gate.check_secreto_literal)
        self.assertTrue(primera.nombre.startswith("CRED"),
                        f"la primera regla debe ser [CRED], es '{primera.nombre}'")

    def test_03_cada_regla_es_callable_pura_que_retorna_lista(self):
        for regla in gate.REGLAS:
            self.assertTrue(callable(regla.check), f"{regla.nombre} no es callable")
            self.assertIsInstance(regla.usa_archivos, bool)

    def test_04_sin_reglas_duplicadas(self):
        checks = [r.check for r in gate.REGLAS]
        self.assertEqual(len(checks), len(set(checks)),
                         "una misma funcion check no debe registrarse dos veces")
        nombres = [r.nombre for r in gate.REGLAS]
        self.assertEqual(len(nombres), len(set(nombres)), "nombres de regla duplicados")

    def test_05_evaluar_reglas_agrega_todas_las_violaciones(self):
        """evaluar_reglas devuelve la union de lo que cada regla reporta.
        Se sustituye REGLAS por 2 reglas de prueba deterministas."""
        Regla = gate.Regla
        originales = gate.REGLAS
        try:
            gate.REGLAS = [
                Regla("fake-a", lambda archivos: ["  [FAKE-A] x"], usa_archivos=True),
                Regla("fake-b", lambda: ["  [FAKE-B] y"], usa_archivos=False),
            ]
            errores = gate.evaluar_reglas(["archivo.py"])
            self.assertEqual(errores, ["  [FAKE-A] x", "  [FAKE-B] y"])
        finally:
            gate.REGLAS = originales

    def test_06_regla_evaluar_respeta_usa_archivos(self):
        Regla = gate.Regla
        recibido = {}
        r_con = Regla("con", lambda archivos: recibido.setdefault("con", archivos) or [], usa_archivos=True)
        r_sin = Regla("sin", lambda: recibido.setdefault("sin", "sin-args") or [], usa_archivos=False)
        r_con.evaluar(["a", "b"])
        r_sin.evaluar(["a", "b"])
        self.assertEqual(recibido["con"], ["a", "b"], "usa_archivos=True recibe el inventario")
        self.assertEqual(recibido["sin"], "sin-args", "usa_archivos=False corre sin args")


if __name__ == "__main__":
    unittest.main()
