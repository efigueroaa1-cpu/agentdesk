"""
core/services/skill_service.py — Libreria de Habilidades (Fase 25, ADR-0023).

Skill Learning sobre la auditoria forense: la tabla `auditoria_ia` ya
registra las herramientas usadas en cada interaccion (herramientas_json,
ADR-0007) — este servicio NO captura nada nuevo, mina lo que ya existe:

  1. identificar_secuencias(): agrupa las interacciones EXITOSAS por su
     secuencia de herramientas y cuenta apariciones — una secuencia que se
     repite es un procedimiento que funciona, no un accidente.
  2. extraer_habilidad(): congela una secuencia como RECETA reutilizable
     (JSON en %APPDATA%/AgentDesk/skills/) con un ejemplo real de uso, y
     la indexa en la Memoria Hermes (tipo="habilidad") para que cualquier
     agente DEL MISMO USUARIO la recupere por similitud semantica.
  3. SkillHarness (registrado como HAT "habilidades" en harness_service)
     inyecta en el prompt las recetas relevantes al mensaje entrante.

[SEMANTIC-PRIVACY] (ADR-0023): las habilidades son conocimiento del
usuario que las aprendio — se minan, guardan y recuperan SIEMPRE dentro
del scope user_id (+ proyecto_id en Hermes). No hay habilidades "de
todos": compartir entre usuarios seria una fuga de know-how entre
operadores (misma logica que ADR-0010 para la memoria).
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_APARICIONES_DEFAULT = 2
MAX_TRAZAS_MINADO = 200


def _slug(nombre: str) -> str:
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    plano = re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-")
    return plano[:64] or "habilidad"


def _dir_skills() -> Path:
    from core.path_manager import data_path
    ruta = data_path("skills/.keep").parent
    return ruta


def identificar_secuencias(
    user_id: str, agente_id: str | None = None,
    min_apariciones: int = MIN_APARICIONES_DEFAULT,
) -> list[dict]:
    """
    Secuencias de herramientas repetidas en interacciones exitosas del
    usuario. Retorna [{secuencia, apariciones, ejemplo}] por frecuencia
    descendente. El filtro user_id es obligatorio (fail-closed).
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("Skills: user_id obligatorio (SEMANTIC-PRIVACY)")
    from core.services.audit_service import consultar

    trazas = consultar(agente_id=agente_id, user_id=user_id, limit=MAX_TRAZAS_MINADO)
    conteo: Counter = Counter()
    ejemplos: dict[tuple, dict] = {}
    for t in trazas:
        if not t.get("exitoso", True):
            continue
        herramientas = tuple(t.get("herramientas") or [])
        if not herramientas:
            continue
        conteo[herramientas] += 1
        # El ejemplo mas reciente basta (consultar retorna descendente por ts)
        ejemplos.setdefault(herramientas, {
            "prompt":    (t.get("prompt") or "")[:400],
            "respuesta": (t.get("respuesta") or "")[:400],
            "agente_id": t.get("agente_id", ""),
        })

    return [
        {"secuencia": list(sec), "apariciones": n, "ejemplo": ejemplos[sec]}
        for sec, n in conteo.most_common()
        if n >= min_apariciones
    ]


def extraer_habilidad(
    nombre: str, user_id: str,
    secuencia: list[str] | None = None,
    descripcion: str = "",
    proyecto_id: str = "",
) -> dict:
    """
    Congela una secuencia como receta reutilizable. Si no se pasa la
    secuencia, usa la mas frecuente del minado. Persiste el JSON en
    skills/ e indexa en Hermes para recuperacion semantica.
    """
    from core.telemetry_otel import medir_paso
    with medir_paso("skills.extraer"):
        if not user_id or not str(user_id).strip():
            raise ValueError("Skills: user_id obligatorio (SEMANTIC-PRIVACY)")

        ejemplo: dict = {}
        if secuencia is None:
            candidatas = identificar_secuencias(user_id)
            if not candidatas:
                raise ValueError(
                    "No hay secuencias de herramientas repetidas y exitosas "
                    "en la auditoria de este usuario — nada que extraer aun."
                )
            secuencia = candidatas[0]["secuencia"]
            ejemplo = candidatas[0]["ejemplo"]

        receta = {
            "slug":        _slug(nombre),
            "nombre":      nombre,
            "descripcion": descripcion or f"Procedimiento aprendido: {' -> '.join(secuencia)}",
            "secuencia_herramientas": list(secuencia),
            "ejemplo":     ejemplo,
            "user_id":     user_id,
            "creada":      time.time(),
            "version":     1,
        }
        ruta = _dir_skills() / f"{receta['slug']}.json"
        ruta.write_text(json.dumps(receta, ensure_ascii=False, indent=2),
                        encoding="utf-8")

        from core.vector_store import PROYECTO_GLOBAL, hermes
        hermes().guardar(
            f"Habilidad: {nombre}. {receta['descripcion']}. "
            f"Herramientas: {' '.join(secuencia)}. "
            f"Ejemplo: {ejemplo.get('prompt', '')}",
            user_id=user_id,
            proyecto_id=proyecto_id or PROYECTO_GLOBAL,
            agente_id="",
            tipo="habilidad",
        )
        logger.info("SKILLS: habilidad '%s' extraida (%d pasos) para user_hash=%s",
                    receta["slug"], len(secuencia), user_id[:12])
        return receta


def listar_habilidades(user_id: str) -> list[dict]:
    """Recetas del usuario (el scope user_id es obligatorio)."""
    if not user_id or not str(user_id).strip():
        raise ValueError("Skills: user_id obligatorio (SEMANTIC-PRIVACY)")
    recetas = []
    for archivo in sorted(_dir_skills().glob("*.json")):
        try:
            receta = json.loads(archivo.read_text(encoding="utf-8"))
            if receta.get("user_id") == user_id:
                recetas.append(receta)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("SKILLS: receta ilegible %s (%s)", archivo.name, exc)
    return recetas


def obtener(slug: str, user_id: str) -> dict | None:
    """Una receta por slug, solo si pertenece al usuario."""
    for receta in listar_habilidades(user_id):
        if receta.get("slug") == slug:
            return receta
    return None


def como_prompt(receta: dict) -> str:
    """Receta como bloque de prompt invocable por cualquier agente."""
    pasos = " -> ".join(receta.get("secuencia_herramientas", []))
    lineas = [
        f"- Habilidad aprendida: {receta.get('nombre')}",
        f"  Procedimiento: usa las herramientas en este orden: {pasos}.",
    ]
    ejemplo = receta.get("ejemplo") or {}
    if ejemplo.get("prompt"):
        lineas.append(f"  Caso resuelto antes: \"{ejemplo['prompt'][:200]}\"")
    return "\n".join(lineas)
