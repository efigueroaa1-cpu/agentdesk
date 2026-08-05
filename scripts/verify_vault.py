"""
scripts/verify_vault.py — Certificación de Soberanía Operativa de Secretos.

Diagnóstico de la cadena de custodia de API keys tras la migración a
Windows Credential Manager (keyring) + vault cifrado (.keyvault). Verifica
que:

  1. Cada clave (Tavily / Groq / Gemini) se resuelve por keyring o vault
     —NUNCA dependiendo de un .env en texto plano.
  2. No existan variables de entorno residuales (os.environ) con esos
     nombres (fuga de secreto en el proceso).
  3. La clave de Tavily es válida contra la API real (dummy check).

Si algo falla, indica EXACTAMENTE en qué capa (Keyring o Vault) se perdió
la referencia. No modifica nada: es solo lectura.

Uso:   python scripts/verify_vault.py
Salida: exit 0 = certificado; exit 1 = falla (revisar log).
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

# La consola de Windows suele ser cp1252: forzar UTF-8 para el log con recuadros.
try:
    sys.stdout.reconfigure(encoding="utf-8")   # type: ignore[union-attr]
except Exception:
    pass

# ── Bootstrap de import: raíz del repo en sys.path ──────────────────────────────
_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

# IMPORTANTE: capturar os.environ ANTES de importar cualquier módulo del core,
# para que un dotenv/autoload no enmascare variables residuales reales.
_ENV_AL_ARRANCAR = {
    k: os.environ.get(k)
    for k in ("AGENTDESK_TAVILY_KEY", "GROQ_API_KEY", "GEMINI_API_KEY")
}

from core import key_vault  # noqa: E402


# Nombre lógico -> variable de entorno registrada en el vault/keyring
CLAVES = {
    "Tavily": "AGENTDESK_TAVILY_KEY",
    "Groq":   "GROQ_API_KEY",
    "Gemini": "GEMINI_API_KEY",
}


def _leer_vault() -> dict:
    """Lee el .keyvault crudo (dict nombre_env -> ciphertext), o {} si no hay."""
    vpath = key_vault._vault_path()
    if not vpath.exists():
        return {}
    try:
        return json.loads(vpath.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"    [WARN] .keyvault ilegible: {exc}")
        return {}


def _mascara(valor: str | None) -> str:
    if not valor:
        return "<vacío>"
    if len(valor) <= 8:
        return "****"
    return f"{valor[:4]}…{valor[-4:]} (len={len(valor)})"


def diagnosticar_capas() -> tuple[bool, str | None]:
    """Resuelve cada clave por capas y reporta la fuente autoritativa.

    Devuelve (todo_ok, tavily_key). Aplica la misma prioridad que
    key_vault.obtener_key: Keyring -> Vault -> Env.
    """
    print("─" * 68)
    print("  CAPA 1/3 · Resolución por capas (Keyring → Vault → Env)")
    print("─" * 68)

    vault_raw = _leer_vault()
    todo_ok = True
    tavily_key: str | None = None

    for etiqueta, nombre_env in CLAVES.items():
        desde_keyring = key_vault._keyring_get(nombre_env)
        desde_vault = None
        if nombre_env in vault_raw:
            desde_vault = key_vault.descifrar(vault_raw[nombre_env])

        # Fuente autoritativa según la prioridad real del sistema
        if desde_keyring:
            fuente, valor = "Keyring (Credential Manager)", desde_keyring
        elif desde_vault:
            fuente, valor = "Vault (.keyvault cifrado)", desde_vault
        else:
            fuente, valor = None, None

        print(f"\n  · {etiqueta} ({nombre_env})")
        print(f"      Keyring : {'OK ' + _mascara(desde_keyring) if desde_keyring else 'AUSENTE'}")
        print(f"      Vault   : {'OK ' + _mascara(desde_vault) if desde_vault else 'AUSENTE'}")

        if valor:
            print(f"      → Fuente autoritativa: {fuente}")
            if not desde_keyring and desde_vault:
                print("      [AVISO] Referencia perdida en la capa KEYRING "
                      "(resuelto por Vault de respaldo).")
        else:
            todo_ok = False
            print("      [FALLA] Referencia perdida en AMBAS capas "
                  "(Keyring y Vault). Clave no recuperable soberanamente.")

        if etiqueta == "Tavily":
            tavily_key = valor

    return todo_ok, tavily_key


def verificar_residuos_env() -> bool:
    """True si NO hay variables de entorno residuales con los nombres de clave."""
    print("\n" + "─" * 68)
    print("  CAPA 2/3 · Variables de entorno residuales (os.environ)")
    print("─" * 68)
    limpio = True
    for etiqueta, nombre_env in CLAVES.items():
        residuo = _ENV_AL_ARRANCAR.get(nombre_env)
        if residuo:
            limpio = False
            print(f"  · {etiqueta:7s} [RESIDUO] {nombre_env} presente en el "
                  f"entorno del proceso → {_mascara(residuo)}")
        else:
            print(f"  · {etiqueta:7s} [OK] sin residuo en os.environ")
    if limpio:
        print("\n  Entorno limpio: ningún secreto expuesto en texto plano en el proceso.")
    else:
        print("\n  [FALLA] Hay secretos en os.environ — el .env/entorno no fue saneado.")
    return limpio


def dummy_check_tavily(tavily_key: str | None) -> bool:
    """Saludo mínimo a la API de Tavily para validar la clave (espeja core.tools)."""
    print("\n" + "─" * 68)
    print("  CAPA 3/3 · Dummy check contra api.tavily.com (validez de clave)")
    print("─" * 68)
    if not tavily_key:
        print("  [FALLA] Sin clave de Tavily recuperable; no se puede validar acceso.")
        return False

    try:
        import httpx
    except ImportError:
        print("  [WARN] httpx no disponible en este entorno; se omite la llamada de red.")
        print("         (La clave SÍ se recuperó por keyring/vault; solo no se validó online.)")
        return True

    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tavily_key,
                    "query": "AgentDesk soberania de secretos ping",
                    "max_results": 1,
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
        if resp.status_code == 200:
            n = len(resp.json().get("results", []))
            print(f"  [OK] Tavily respondió 200 · {n} resultado(s). Clave VÁLIDA.")
            return True
        if resp.status_code in (401, 403):
            print(f"  [FALLA] Tavily {resp.status_code}: clave RECHAZADA "
                  f"(rotación no aplicada o clave inválida). {resp.text[:120]}")
            return False
        print(f"  [WARN] Tavily {resp.status_code}: {resp.text[:120]}")
        print("         Clave recuperada, pero la API respondió un estado inesperado.")
        return False
    except Exception as exc:
        print(f"  [WARN] No se pudo contactar Tavily ({exc}). "
              "Sin red no se certifica la validez online.")
        return False


def main() -> int:
    print("\n" + "=" * 68)
    print("  AgentDesk · Certificación de Soberanía de Secretos  (v1.4.0)")
    print("=" * 68)

    capas_ok, tavily_key = diagnosticar_capas()
    env_limpio = verificar_residuos_env()
    tavily_ok = dummy_check_tavily(tavily_key)

    print("\n" + "=" * 68)
    if capas_ok and env_limpio and tavily_ok:
        print("  [OK] Soberanía de Secretos Certificada - v1.4.0")
        print("=" * 68 + "\n")
        return 0

    print("  [X] Certificación FALLIDA. Detalle:")
    if not capas_ok:
        print("      - Alguna clave no se recupera por Keyring/Vault (ver CAPA 1).")
    if not env_limpio:
        print("      - Hay secretos residuales en os.environ (ver CAPA 2).")
    if not tavily_ok:
        print("      - La clave de Tavily no se validó contra la API (ver CAPA 3).")
    print("=" * 68 + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
