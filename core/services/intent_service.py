"""
core/services/intent_service.py — Copiloto de Intencion (Fase 27, ADR-0025).

Traduce un OBJETIVO en lenguaje natural a un plan estructurado y seguro:

    planificar(objetivo) -> {
        pasos:          tareas para agentes (con agente sugerido y duracion),
        habilidades:    recetas Hermes relevantes al objetivo (Fase 25),
        acciones_ot:    comandos OT — SOLO los que pasan el filtro de
                        limites fisicos (Fase 26); los inseguros se
                        reportan aparte como descartados, jamas se ofrecen,
        gantt_propuesto: tareas listas para insertar en el Gantt P6,
    }

    aplicar_en_gantt(plan, proyecto_id) -> inserta las tareas y proyecta
        el impacto en la Curva S ANTES vs DESPUES (BAC/fin proyectado).

Arquitectura de seguridad ([INTENT-SAFETY], ADR-0025):
  - El LLM redacta el plan (pasos y justificaciones) pero NUNCA decide
    que accion OT es segura: toda accion candidata pasa por
    ot_service.validar() (limites fisicos deterministas) antes de
    aparecer en el plan. Las que fallan van a `descartadas_por_filtro`.
  - Ejecutar sigue siendo Human-in-the-loop (ADR-0024): el plan PROPONE;
    las acciones OT entran a la bandeja de aprobacion, no a la planta.
  - Sin LLM disponible (offline/mock) el motor degrada a un planificador
    determinista por reglas — el copiloto nunca queda mudo.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

DURACION_DEFECTO_DIAS = 1.0
MAX_PASOS_PLAN = 8

_PROMPT_PLAN = """Eres el planificador de AgentDesk. Convierte el OBJETIVO del
operador en un plan JSON. Responde SOLO el JSON, sin texto extra:
{{
  "pasos": [{{"titulo": str, "descripcion": str, "agente_sugerido": str,
             "duracion_dias": number}}],
  "acciones_ot": [{{"adaptador": "modbus"|"mqtt", "tag_id": str,
                   "valor": number, "justificacion": str}}]
}}
Tags OT disponibles (con sus limites fisicos): {catalogo}
Habilidades aprendidas relevantes: {habilidades}
OBJETIVO: {objetivo}"""


def _catalogo_ot() -> list[dict]:
    """Tags escribibles registrados (via el servicio OT, nunca adapters directo)."""
    from core.services.ot_command_service import ot_service
    catalogo = []
    for nombre in ot_service.adaptadores():
        ad = ot_service._adaptadores[nombre]
        for tag in ad.actuadores():
            catalogo.append({"adaptador": nombre, "tag_id": tag["id"],
                             "nombre": tag.get("nombre", tag["id"]),
                             "min": tag["min_escritura"], "max": tag["max_escritura"]})
    return catalogo


def _habilidades_relevantes(objetivo: str, user_id: str, proyecto_id: str) -> list[dict]:
    """Recetas Hermes relacionadas al objetivo (Fase 25) — scope estricto."""
    from core.services import skill_service
    from core.vector_store import hermes
    coincidencias = hermes().buscar(
        objetivo, user_id=user_id, proyecto_id=proyecto_id,
        tipo="habilidad", top_k=3, umbral=0.1,
    )
    recetas = []
    for c in coincidencias:
        for receta in skill_service.listar_habilidades(user_id):
            if receta.get("nombre") and receta["nombre"] in c["texto"]:
                recetas.append(receta)
                break
    return recetas


async def _plan_llm(objetivo: str, catalogo: list[dict],
                    habilidades: list[dict]) -> dict | None:
    """Borrador del plan via la cadena LLM resiliente; None si no hay JSON valido."""
    try:
        from core.services.llm_service import llm_service
        resultado = await llm_service.generar(
            _PROMPT_PLAN.format(
                catalogo=json.dumps(catalogo, ensure_ascii=False),
                habilidades=json.dumps([h.get("nombre") for h in habilidades],
                                       ensure_ascii=False),
                objetivo=objetivo,
            ),
            temperatura=0.2,
        )
        crudo = resultado.get("texto", "")
        m = re.search(r"\{.*\}", crudo, re.S)
        if not m:
            return None
        plan = json.loads(m.group(0))
        if not isinstance(plan.get("pasos"), list):
            return None
        return plan
    except Exception as exc:
        logger.info("Copiloto: LLM no disponible o sin JSON (%s) — plan por reglas", exc)
        return None


def _plan_por_reglas(objetivo: str, catalogo: list[dict],
                     habilidades: list[dict]) -> dict:
    """
    Planificador determinista (fallback offline): diagnostico + habilidad
    aplicable + accion OT solo si el objetivo menciona un tag/actuador
    conocido. Nunca inventa valores: usa los de la habilidad, o ninguno.
    """
    objetivo_l = objetivo.lower()
    pasos = [{
        "titulo": "Diagnostico del estado actual",
        "descripcion": f"Analizar telemetria e historial relacionados con: {objetivo}",
        "agente_sugerido": "", "duracion_dias": DURACION_DEFECTO_DIAS,
    }]
    acciones = []
    for receta in habilidades:
        pasos.append({
            "titulo": f"Aplicar habilidad: {receta['nombre']}",
            "descripcion": " -> ".join(receta.get("secuencia_herramientas", [])),
            "agente_sugerido": (receta.get("ejemplo") or {}).get("agente_id", ""),
            "duracion_dias": DURACION_DEFECTO_DIAS,
        })
        acciones.extend(dict(c, justificacion=f"Habilidad '{receta['nombre']}'")
                        for c in receta.get("comandos_ot", []))
    for tag in catalogo:
        nombre_l = tag["nombre"].lower()
        if tag["tag_id"] in objetivo_l or any(
                palabra in objetivo_l for palabra in nombre_l.split() if len(palabra) > 4):
            if not any(a["tag_id"] == tag["tag_id"] for a in acciones):
                pasos.append({
                    "titulo": f"Evaluar actuador {tag['nombre']}",
                    "descripcion": (f"Revisar si corresponde actuar sobre "
                                    f"{tag['tag_id']} (limites {tag['min']}-{tag['max']})"),
                    "agente_sugerido": "", "duracion_dias": 0.5,
                })
    pasos.append({
        "titulo": "Verificacion y cierre",
        "descripcion": "Confirmar KPIs post-accion y documentar el resultado",
        "agente_sugerido": "", "duracion_dias": 0.5,
    })
    return {"pasos": pasos, "acciones_ot": acciones}


def _filtrar_acciones_ot(acciones: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    [INTENT-SAFETY]: cada accion candidata pasa por ot_service.validar()
    (limites fisicos deterministas de la Fase 26). Las inseguras JAMAS se
    ofrecen al usuario: van a descartadas, con el motivo.
    """
    from core.services.ot_command_service import ot_service
    seguras, descartadas = [], []
    for a in acciones:
        try:
            ok, motivo = ot_service.validar(
                a.get("adaptador", ""), a.get("tag_id", ""), a.get("valor"))
        except Exception as exc:
            ok, motivo = False, str(exc)
        if ok:
            seguras.append(a)
        else:
            logger.warning("AUDITORIA_SEGURIDAD: Copiloto descarto accion OT "
                           "insegura — %r (%s)", a, motivo)
            descartadas.append({**a, "motivo_descarte": motivo})
    return seguras, descartadas


async def planificar(objetivo: str, *, user_id: str,
                     proyecto_id: str = "") -> dict:
    """Objetivo en lenguaje natural -> plan estructurado, seguro y trazable."""
    from core.telemetry_otel import medir_paso
    from core.vector_store import PROYECTO_GLOBAL

    if not objetivo or not objetivo.strip():
        raise ValueError("Copiloto: el objetivo no puede estar vacio")
    if not user_id or not str(user_id).strip():
        raise ValueError("Copiloto: user_id obligatorio (SEMANTIC-PRIVACY)")
    ambito = proyecto_id or PROYECTO_GLOBAL

    with medir_paso("copiloto.planificar"):
        catalogo    = _catalogo_ot()
        habilidades = _habilidades_relevantes(objetivo, user_id, ambito)

        plan = await _plan_llm(objetivo, catalogo, habilidades)
        origen = "llm"
        if plan is None:
            plan, origen = _plan_por_reglas(objetivo, catalogo, habilidades), "reglas"

        pasos = plan.get("pasos", [])[:MAX_PASOS_PLAN]
        seguras, descartadas = _filtrar_acciones_ot(plan.get("acciones_ot", []))

        gantt_propuesto = [
            {"nombre": p["titulo"][:120],
             "duracion_dias": max(0.25, float(p.get("duracion_dias") or DURACION_DEFECTO_DIAS)),
             "agente_id": p.get("agente_sugerido", "")}
            for p in pasos
        ]

        # Trazabilidad forense del plan (best-effort, ADR-0007)
        try:
            from core.services.audit_service import registrar_interaccion
            registrar_interaccion(
                tipo="copiloto_plan", agente_id="copiloto", user_id=user_id,
                prompt=objetivo,
                respuesta=json.dumps({"pasos": len(pasos), "ot": len(seguras),
                                      "descartadas": len(descartadas)}),
                proyecto_id=proyecto_id, exitoso=True,
            )
        except Exception:
            pass

        return {
            "objetivo": objetivo, "origen": origen,
            "pasos": pasos,
            "habilidades": [h.get("nombre") for h in habilidades],
            "acciones_ot": seguras,
            "descartadas_por_filtro": descartadas,
            "gantt_propuesto": gantt_propuesto,
        }


def aplicar_en_gantt(plan: dict, proyecto_id: str, *, user_id: str) -> dict:
    """
    Auto-programacion en Gantt P6: inserta las tareas propuestas en
    secuencia (dependencia Fin->Inicio) y proyecta el impacto en la
    Curva S (BAC y fin proyectado ANTES vs DESPUES). Las acciones OT del
    plan se PROPONEN a la bandeja Human-in-the-loop — jamas se ejecutan.
    """
    from datetime import timedelta
    from core.analytics import motor_analitica
    from core.gantt import motor_gantt
    from core.services.ot_command_service import ot_service
    from core.timeutil import utcnow

    if not proyecto_id or not proyecto_id.strip():
        raise ValueError("Copiloto: proyecto_id obligatorio para aplicar en Gantt")

    curva_antes = motor_analitica.calcular_curva_s(proyecto_id)

    creadas, inicio, anterior_id = [], utcnow(), None
    for t in plan.get("gantt_propuesto", []):
        tarea = motor_gantt.crear_tarea({
            "proyecto_id":   proyecto_id,
            "nombre":        t["nombre"],
            "agente_id":     t.get("agente_id", ""),
            "inicio_plan":   inicio,
            "duracion_dias": t["duracion_dias"],
            "dependencias":  [anterior_id] if anterior_id else [],
        })
        creadas.append(tarea)
        anterior_id = tarea["id"]
        inicio = inicio + timedelta(days=t["duracion_dias"])

    propuestas_ot = [
        ot_service.proponer(
            adaptador=a["adaptador"], tag_id=a["tag_id"], valor=a["valor"],
            justificacion=a.get("justificacion", plan.get("objetivo", "")),
            agente_id="copiloto", user_id=user_id,
        )
        for a in plan.get("acciones_ot", [])
    ]

    curva_despues = motor_analitica.calcular_curva_s(proyecto_id)
    return {
        "tareas_creadas": creadas,
        "propuestas_ot":  propuestas_ot,
        "impacto_curva_s": {
            "antes":   curva_antes.get("kpis", {}),
            "despues": curva_despues.get("kpis", {}),
        },
    }
