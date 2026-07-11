"""
core/gantt.py — Motor de Planificación Gantt con Ruta Crítica (CPM).

Algoritmo:
  Forward pass  — calcula ES/EF en orden topológico (Kahn).
  Backward pass — calcula LS/LF en orden topológico inverso.
  Float/Holgura — LS - ES (días).
  Ruta crítica  — tareas con holgura ≈ 0.

Dependencias soportadas: Fin a Inicio (FS) únicamente.
Unidad de tiempo: días calendario (float, permite fracciones).

Persistencia: SQLAlchemy → agentdesk.db (tabla gantt_tasks).
Validación:   Pydantic v2 en toda entrada; rollback implícito si falla.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

from pydantic import ValidationError

from core.schemas import GanttTaskInput, GanttProgresoUpdate

logger = logging.getLogger(__name__)

_TOLERANCIA_CRITICA = 0.05   # días — holgura < esto → tarea crítica


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

class MotorGantt:
    """
    Gestiona cronogramas Gantt por proyecto.

    Toda operación de escritura valida la entrada con Pydantic antes de tocar
    la DB. Si la validación falla el estado previo se conserva (rollback).
    Tras cada mutación se recalcula la Ruta Crítica del proyecto completo.
    """

    # ── CRUD de tareas ──────────────────────────────────────────────────────────

    def crear_tarea(self, datos: dict) -> dict:
        """
        Crea una tarea y recalcula la Ruta Crítica del proyecto.
        Retorna la tarea creada como dict, o raise ValueError si la validación falla.
        """
        from core.database import GanttTask, get_session

        try:
            inp = GanttTaskInput.model_validate(datos)
        except ValidationError as e:
            logger.error("crear_tarea: validación fallida — %s", e)
            raise ValueError(str(e)) from e

        fin_plan = inp.inicio_plan + timedelta(days=inp.duracion_dias)

        with get_session() as s:
            tarea = GanttTask(
                proyecto_id=inp.proyecto_id,
                nombre=inp.nombre,
                agente_id=inp.agente_id,
                inicio_plan=inp.inicio_plan,
                fin_plan=fin_plan,
                duracion_dias=inp.duracion_dias,
                dependencias_json=json.dumps(inp.dependencias),
                color=inp.color,
                pct_completado=0.0,
            )
            s.add(tarea)
            s.commit()
            nuevo_id = tarea.id
            logger.info("Tarea creada: id=%s proyecto=%s nombre='%s'",
                        nuevo_id, inp.proyecto_id, inp.nombre)

        # Recalcular CPM para el proyecto completo
        self._recalcular_cpm(inp.proyecto_id)

        return self.obtener_tarea(nuevo_id)

    def actualizar_tarea(self, tarea_id: int, datos: dict) -> dict:
        """
        Actualiza una tarea (campos parciales). Recalcula CPM tras el cambio.
        Aplica rollback Pydantic: si la duración o inicio son inválidos, no toca la DB.
        """
        from core.database import GanttTask, get_session

        with get_session() as s:
            tarea = s.get(GanttTask, tarea_id)
            if tarea is None:
                raise ValueError(f"Tarea {tarea_id} no encontrada")
            proyecto_id = tarea.proyecto_id

            # Validar solo los campos modificados
            snapshot = tarea.to_dict()

        # Construir payload completo para la validación
        payload_completo = {
            "proyecto_id":   snapshot["proyecto_id"],
            "nombre":        datos.get("nombre",        snapshot["nombre"]),
            "agente_id":     datos.get("agente_id",     snapshot["agente_id"]),
            "inicio_plan":   datos.get("inicio_plan",   snapshot["inicio_plan"]),
            "duracion_dias": datos.get("duracion_dias", snapshot["duracion_dias"]),
            "dependencias":  datos.get("dependencias",  snapshot["dependencias"]),
            "color":         datos.get("color",         snapshot["color"]),
        }

        try:
            inp = GanttTaskInput.model_validate(payload_completo)
        except ValidationError as e:
            logger.error("actualizar_tarea %s: validación fallida — rollback. %s", tarea_id, e)
            raise ValueError(str(e)) from e

        fin_plan = inp.inicio_plan + timedelta(days=inp.duracion_dias)

        with get_session() as s:
            tarea = s.get(GanttTask, tarea_id)
            tarea.nombre        = inp.nombre
            tarea.agente_id     = inp.agente_id
            tarea.inicio_plan   = inp.inicio_plan
            tarea.fin_plan      = fin_plan
            tarea.duracion_dias = inp.duracion_dias
            tarea.dependencias_json = json.dumps(inp.dependencias)
            tarea.color         = inp.color
            s.commit()

        # Recalcular CPM — propaga cambios a todas las sucesoras
        self._recalcular_cpm(proyecto_id)

        return self.obtener_tarea(tarea_id)

    def actualizar_progreso(self, tarea_id: int, datos: dict) -> dict:
        """
        Actualiza el avance (pct_completado) de una tarea con validación Pydantic.
        Rollback si el valor está fuera de rango.
        """
        from core.database import GanttTask, get_session

        try:
            upd = GanttProgresoUpdate.model_validate(datos)
        except ValidationError as e:
            logger.error("actualizar_progreso %s: validación fallida — %s", tarea_id, e)
            raise ValueError(str(e)) from e

        with get_session() as s:
            tarea = s.get(GanttTask, tarea_id)
            if tarea is None:
                raise ValueError(f"Tarea {tarea_id} no encontrada")
            tarea.pct_completado = upd.pct_completado
            if upd.inicio_real:
                tarea.inicio_real = upd.inicio_real
            if upd.fin_real:
                tarea.fin_real = upd.fin_real
            s.commit()
            resultado = tarea.to_dict()

        logger.info("Progreso actualizado: tarea=%s pct=%.1f%%", tarea_id, upd.pct_completado)
        return resultado

    def eliminar_tarea(self, tarea_id: int) -> bool:
        """Elimina la tarea y recalcula CPM del proyecto."""
        from core.database import GanttTask, get_session

        with get_session() as s:
            tarea = s.get(GanttTask, tarea_id)
            if tarea is None:
                return False
            proyecto_id = tarea.proyecto_id

            # Limpiar referencias a esta tarea en las demás
            tareas_proyecto = (
                s.query(GanttTask)
                .filter(GanttTask.proyecto_id == proyecto_id)
                .all()
            )
            for t in tareas_proyecto:
                deps = json.loads(t.dependencias_json or "[]")
                if tarea_id in deps:
                    deps.remove(tarea_id)
                    t.dependencias_json = json.dumps(deps)

            s.delete(tarea)
            s.commit()

        self._recalcular_cpm(proyecto_id)
        return True

    # ── Consultas ───────────────────────────────────────────────────────────────

    def obtener_tarea(self, tarea_id: int) -> dict:
        from core.database import GanttTask, get_session
        with get_session() as s:
            t = s.get(GanttTask, tarea_id)
            if t is None:
                raise ValueError(f"Tarea {tarea_id} no encontrada")
            return t.to_dict()

    def obtener_proyecto(self, proyecto_id: str) -> dict:
        """Retorna todas las tareas del proyecto con métricas de avance."""
        from core.database import GanttTask, get_session

        with get_session() as s:
            tareas = (
                s.query(GanttTask)
                .filter(GanttTask.proyecto_id == proyecto_id)
                .order_by(GanttTask.inicio_plan)
                .all()
            )
            tareas_dict = [t.to_dict() for t in tareas]

        if not tareas_dict:
            return {"proyecto_id": proyecto_id, "tareas": [], "resumen": {}}

        # Métricas de resumen
        n = len(tareas_dict)
        pct_prom = sum(t["pct_completado"] for t in tareas_dict) / n
        n_criticas = sum(1 for t in tareas_dict if t["en_ruta_critica"])
        fechas_inicio = [t["inicio_plan"] for t in tareas_dict if t["inicio_plan"]]
        fechas_fin    = [t["fin_plan"]    for t in tareas_dict if t["fin_plan"]]

        return {
            "proyecto_id": proyecto_id,
            "tareas":      tareas_dict,
            "resumen": {
                "total_tareas":     n,
                "pct_avance":       round(pct_prom, 1),
                "tareas_criticas":  n_criticas,
                "fecha_inicio":     min(fechas_inicio) if fechas_inicio else None,
                "fecha_fin":        max(fechas_fin)    if fechas_fin    else None,
            },
        }

    def listar_proyectos(self) -> list[dict]:
        """Lista todos los proyectos distintos con su fecha y avance."""
        from core.database import GanttTask, get_session
        from sqlalchemy import distinct

        with get_session() as s:
            ids = [r[0] for r in s.query(distinct(GanttTask.proyecto_id)).all()]

        return [
            {
                "proyecto_id": pid,
                "resumen":     self.obtener_proyecto(pid)["resumen"],
            }
            for pid in ids
        ]

    # ── Actualización de progreso por agente (desde telemetría WS) ──────────────

    def actualizar_progreso_por_agente(
        self,
        agente_id: str,
        incremento_pct: float = 10.0,
    ) -> list[dict]:
        """
        Incrementa el progreso de las tareas en curso del agente.
        Llamado desde el WebSocketLogHandler cuando llega un evento
        de telemetría con status='ok' para ese agente.

        Retorna lista de tareas actualizadas.
        """
        from core.database import GanttTask, get_session

        actualizadas = []
        with get_session() as s:
            tareas = (
                s.query(GanttTask)
                .filter(
                    GanttTask.agente_id == agente_id,
                    GanttTask.pct_completado < 100.0,
                    GanttTask.fin_real.is_(None),   # sin fecha de fin real = en curso
                )
                .all()
            )
            for t in tareas:
                nuevo_pct = min(100.0, round((t.pct_completado or 0.0) + incremento_pct, 1))
                t.pct_completado = nuevo_pct
                if nuevo_pct >= 100.0:
                    t.fin_real = datetime.utcnow()
                actualizadas.append(t.to_dict())
            s.commit()

        if actualizadas:
            logger.info(
                "Progreso automático: agente=%s tareas_actualizadas=%d",
                agente_id, len(actualizadas),
            )
        return actualizadas

    # ── CPM: Forward + Backward pass ──────────────────────────────────────────

    def _recalcular_cpm(self, proyecto_id: str) -> None:
        """
        Ejecuta el algoritmo CPM completo sobre el proyecto y persiste los resultados.

        Forward pass  (orden topológico):
          ES[i] = max(EF[j] for j in predecesoras[i])  ← si no hay predecesoras: inicio_plan
          EF[i] = ES[i] + duracion_dias[i]

        Backward pass (orden topológico inverso):
          LF[i] = min(LS[j] for j in sucesoras[i])     ← si no hay sucesoras: max(EF)
          LS[i] = LF[i] - duracion_dias[i]

        Float[i] = (LS[i] - ES[i]).days
        Crítica   = Float < _TOLERANCIA_CRITICA días
        """
        from core.database import GanttTask, get_session

        with get_session() as s:
            tareas = (
                s.query(GanttTask)
                .filter(GanttTask.proyecto_id == proyecto_id)
                .all()
            )
            if not tareas:
                return

            # Mapas de trabajo
            id_a_tarea = {t.id: t for t in tareas}
            deps:   dict[int, list[int]] = {}   # tarea_id → lista de predecesoras
            sucs:   dict[int, list[int]] = defaultdict(list)
            grado:  dict[int, int]       = {}   # in-degree para Kahn

            for t in tareas:
                predecs = json.loads(t.dependencias_json or "[]")
                predecs = [p for p in predecs if p in id_a_tarea]   # sanear referencias rotas
                deps[t.id] = predecs
                grado[t.id] = len(predecs)
                for p in predecs:
                    sucs[p].append(t.id)

            # ── Orden topológico (Kahn) ────────────────────────────────────────
            cola   = deque(tid for tid, g in grado.items() if g == 0)
            orden: list[int] = []

            while cola:
                tid = cola.popleft()
                orden.append(tid)
                for suc_id in sucs[tid]:
                    grado[suc_id] -= 1
                    if grado[suc_id] == 0:
                        cola.append(suc_id)

            if len(orden) < len(tareas):
                # Ciclo detectado — imposible calcular CPM; loguear y salir
                ciclo_ids = set(id_a_tarea.keys()) - set(orden)
                logger.error(
                    "CPM: ciclo de dependencias detectado en proyecto '%s'. "
                    "Tareas involucradas: %s",
                    proyecto_id, ciclo_ids,
                )
                return

            # ── Forward pass ───────────────────────────────────────────────────
            ES: dict[int, datetime] = {}
            EF: dict[int, datetime] = {}

            for tid in orden:
                t = id_a_tarea[tid]
                if not deps[tid]:
                    ES[tid] = t.inicio_plan
                else:
                    ES[tid] = max(EF[p] for p in deps[tid])
                EF[tid] = ES[tid] + timedelta(days=t.duracion_dias)

            # ── Backward pass ──────────────────────────────────────────────────
            fin_proyecto = max(EF.values())

            LF: dict[int, datetime] = {}
            LS: dict[int, datetime] = {}

            for tid in reversed(orden):
                t = id_a_tarea[tid]
                if not sucs[tid]:
                    LF[tid] = fin_proyecto
                else:
                    LF[tid] = min(LS[s] for s in sucs[tid])
                LS[tid] = LF[tid] - timedelta(days=t.duracion_dias)

            # ── Actualizar DB ──────────────────────────────────────────────────
            for tid in orden:
                t   = id_a_tarea[tid]
                hol = (LS[tid] - ES[tid]).total_seconds() / 86400
                t.es             = ES[tid]
                t.ef             = EF[tid]
                t.ls             = LS[tid]
                t.lf             = LF[tid]
                t.holgura_dias   = round(hol, 4)
                t.en_ruta_critica = hol < _TOLERANCIA_CRITICA
                # Actualizar fin_plan con la fecha calculada por CPM
                t.fin_plan = EF[tid]

            s.commit()

        n_criticas = sum(1 for tid in orden
                         if (LS[tid] - ES[tid]).total_seconds() / 86400 < _TOLERANCIA_CRITICA)
        logger.info(
            "CPM recalculado: proyecto='%s' tareas=%d críticas=%d fin=%s",
            proyecto_id, len(orden), n_criticas,
            fin_proyecto.strftime("%Y-%m-%d"),
        )


# ── Singleton ──────────────────────────────────────────────────────────────────
motor_gantt = MotorGantt()
