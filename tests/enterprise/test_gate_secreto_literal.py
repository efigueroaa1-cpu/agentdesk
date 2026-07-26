# -*- coding: utf-8 -*-
"""
tests/enterprise/test_gate_secreto_literal.py — Regla [CRED] del Guardian:
deteccion de secretos literales hardcodeados (2026-07-26).

Regresion del incidente real: una API key de Tavily (_TAVILY_KEY = "tvly-...")
vivio en un repo PUBLICO porque RE_CRED_DEFECTO solo miraba valores debiles
conocidos y el nombre '_TAVILY_KEY' no contenia password/secret/api_key/token.
check_secreto_literal() detecta el VALOR por su prefijo de proveedor.

Correr:  python -m unittest tests.enterprise.test_gate_secreto_literal -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import gate  # noqa: E402


class TestSecretoLiteral(unittest.TestCase):

    def _escanear(self, contenido: str, nombre: str = "modulo.py") -> list[str]:
        """Escribe un archivo temporal y corre la regla sobre el, con el path
        relativo que la regla espera."""
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / nombre
            ruta.write_text(contenido, encoding="utf-8")
            orig = gate.RAIZ
            try:
                gate.RAIZ = Path(d)
                return gate.check_secreto_literal([nombre])
            finally:
                gate.RAIZ = orig

    # Las claves sinteticas se CONSTRUYEN por concatenacion: asi el codigo
    # fuente de este test NO contiene un literal contiguo que dispare la
    # propia regla que prueba (mismo motivo por el que gate.py se autoexcluye).
    _CUERPO = "a1B2c3D4e5F6g7H8i9J0kLmNoPqR"   # 28 chars, suficiente entropia

    def test_01_tavily_hardcodeada_se_detecta(self):
        err = self._escanear(f'_TAVILY_KEY = "tvly-{self._CUERPO}"\n')
        self.assertTrue(err, "una clave tvly- literal debe ser detectada")
        self.assertIn("[CRED]", err[0])

    def test_02_no_imprime_el_valor_del_secreto(self):
        err = self._escanear(f'K = "sk-{self._CUERPO}"\n')
        self.assertTrue(err)
        self.assertNotIn(self._CUERPO, err[0],
                         "el gate NUNCA debe volcar el valor del secreto a su salida")

    def test_03_google_groq_github_privatekey(self):
        casos = [f'"AIza{self._CUERPO}{self._CUERPO}"',
                 f'"gsk_{self._CUERPO}"',
                 f'"ghp_{self._CUERPO}{self._CUERPO}"',
                 "-----BEGIN RSA PRIVATE " + "KEY-----"]
        for lit in casos:
            self.assertTrue(self._escanear(f"x = {lit}\n"),
                            f"debe detectar: {lit[:10]}...")

    def test_04_lectura_desde_accesor_no_es_secreto(self):
        err = self._escanear('_TAVILY_KEY = obtener_key("AGENTDESK_TAVILY_KEY") or ""\n')
        self.assertEqual(err, [], "leer del accesor sancionado NO es un secreto hardcodeado")

    def test_05_placeholder_corto_no_dispara(self):
        err = self._escanear('EJEMPLO = "tvly-XXXX"\n')
        self.assertEqual(err, [], "un placeholder corto no alcanza el umbral de entropia")

    def test_06_el_archivo_env_se_excluye(self):
        err = self._escanear(f'AGENTDESK_TAVILY_KEY=tvly-{self._CUERPO}\n', nombre=".env")
        self.assertEqual(err, [], ".env (gitignored) es el lugar legitimo de los secretos")


if __name__ == "__main__":
    unittest.main()
