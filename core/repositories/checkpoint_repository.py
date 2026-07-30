"""
core/repositories/checkpoint_repository.py — Persistencia de estados parciales
de una corrida batch (Soberania de Datos).

Cada agente que completa su reporte en una corrida (ejecutar_todos_paralelo)
escribe una fila (corrida_id, agente_id) con su resultado. Si la corrida se
interrumpe, al relanzarla con el mismo corrida_id los agentes ya completados
se leen del checkpoint en vez de re-ejecutarse.

El modelo vive aqui (no en core/database.py) para no crecer ese modulo por
encima de su linea base de trinquete. La tabla se gobierna por Alembic
(migrations/); _asegurar_tabla() es una red de seguridad para el camino
degradado en el que Alembic no esta disponible.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from core.database import Base, get_session
from core.timeutil import utcnow

logger = logging.getLogger(__name__)


class CheckpointCorrida(Base):
    """Resultado persistido de un agente dentro de una corrida batch."""

    __tablename__ = "checkpoint_corrida"
    __table_args__ = (
        UniqueConstraint("corrida_id", "agente_id",
                         name="uq_checkpoint_corrida_agente"),
    )

    id             = Column(Integer, primary_key=True)
    corrida_id     = Column(String(120), index=True, nullable=False)
    agente_id      = Column(String(120), index=True, nullable=False)
    estado         = Column(String(20), default="completado", nullable=False)
    resultado_json = Column(Text, nullable=False)
    ts             = Column(DateTime, default=utcnow)


_TABLA_ASEGURADA = False


def _asegurar_tabla() -> None:
    """Crea checkpoint_corrida si no existe (checkfirst). Solo actua de verdad
    cuando el esquema no lo creo Alembic; en el flujo normal es un no-op."""
    global _TABLA_ASEGURADA
    if _TABLA_ASEGURADA:
        return
    try:
        import core.database as db
        if db._engine is None:
            db.init_db()
        CheckpointCorrida.__table__.create(bind=db._engine, checkfirst=True)
        _TABLA_ASEGURADA = True
    except Exception as exc:
        logger.debug("checkpoint: no se pudo asegurar la tabla (%s)", exc)


def guardar_checkpoint(corrida_id: str, agente_id: str, resultado: dict) -> None:
    """Escribe (o actualiza) el resultado de un agente de forma atomica.

    La escritura es una unica transaccion (commit): SQLite y PostgreSQL la
    aplican completa o no la aplican — un corte a mitad no deja una fila
    parcial. La restriccion unica (corrida_id, agente_id) hace la operacion
    idempotente frente a reintentos.
    """
    _asegurar_tabla()
    payload = json.dumps(resultado, ensure_ascii=False)
    with get_session() as s:
        fila = (s.query(CheckpointCorrida)
                 .filter_by(corrida_id=corrida_id, agente_id=agente_id)
                 .first())
        if fila is not None:
            fila.resultado_json = payload
            fila.estado = "completado"
            fila.ts = utcnow()
        else:
            s.add(CheckpointCorrida(
                corrida_id=corrida_id, agente_id=agente_id,
                estado="completado", resultado_json=payload,
            ))
        s.commit()


def obtener_checkpoints(corrida_id: str) -> dict[str, dict]:
    """Devuelve {agente_id: resultado} de los agentes ya completados."""
    _asegurar_tabla()
    salida: dict[str, dict] = {}
    with get_session() as s:
        filas = (s.query(CheckpointCorrida)
                  .filter_by(corrida_id=corrida_id, estado="completado")
                  .all())
        for f in filas:
            try:
                salida[f.agente_id] = json.loads(f.resultado_json)
            except (ValueError, TypeError):
                continue
    return salida


def limpiar_checkpoints(corrida_id: str) -> int:
    """Borra los checkpoints de una corrida (tras completarla al 100%)."""
    _asegurar_tabla()
    with get_session() as s:
        n = (s.query(CheckpointCorrida)
              .filter_by(corrida_id=corrida_id)
              .delete())
        s.commit()
        return n
