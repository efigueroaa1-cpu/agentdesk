"""
core/memory.py — Memoria persistente de conversaciones por agente.

Cada agente tiene un historial de conversaciones guardado en SQLite.
Cuando el agente responde, incluye el contexto de los últimos N mensajes
para que la respuesta sea coherente con la conversación anterior.

Tablas:
  conversaciones  — sesiones de chat por agente
  mensajes        — mensajes individuales de cada sesión
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from core.database import Base, get_session


class Conversacion(Base):
    __tablename__ = "conversaciones"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    agente_id   = Column(String(64), nullable=False, index=True)
    sesion_id   = Column(String(64), nullable=False, index=True)
    ts_inicio   = Column(DateTime, default=datetime.utcnow)
    ts_ultimo   = Column(DateTime, default=datetime.utcnow)
    resumen     = Column(Text, default="")   # resumen auto-generado


class Mensaje(Base):
    __tablename__ = "mensajes"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    conversacion_id= Column(Integer, ForeignKey("conversaciones.id"), nullable=False, index=True)
    agente_id      = Column(String(64), index=True)
    sesion_id      = Column(String(64), index=True)
    rol            = Column(String(16))   # "usuario" | "agente"
    contenido      = Column(Text)
    ts             = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":       self.id,
            "rol":      self.rol,
            "contenido":self.contenido,
            "ts":       self.ts.isoformat() if self.ts else None,
        }


def _asegurar_tablas():
    """Crea las tablas si no existen."""
    from core.database import _engine, Base as _Base
    if _engine:
        Conversacion.__table__.create(_engine, checkfirst=True)
        Mensaje.__table__.create(_engine, checkfirst=True)


# ── API pública ────────────────────────────────────────────────────────────────

def guardar_mensaje(
    agente_id: str,
    sesion_id: str,
    rol: str,
    contenido: str,
) -> None:
    """Guarda un mensaje en la memoria de la conversación."""
    try:
        _asegurar_tablas()
        with get_session() as s:
            # Crear/actualizar conversación
            conv = s.query(Conversacion).filter(
                Conversacion.agente_id == agente_id,
                Conversacion.sesion_id == sesion_id,
            ).first()
            if not conv:
                conv = Conversacion(agente_id=agente_id, sesion_id=sesion_id)
                s.add(conv)
                s.flush()
            else:
                conv.ts_ultimo = datetime.utcnow()

            # Guardar mensaje
            s.add(Mensaje(
                conversacion_id=conv.id,
                agente_id=agente_id,
                sesion_id=sesion_id,
                rol=rol,
                contenido=str(contenido)[:4000],
            ))
            s.commit()
    except Exception:
        pass   # La memoria no debe interrumpir el flujo principal


def get_contexto(
    agente_id: str,
    sesion_id: str,
    n_mensajes: int = 10,
) -> str:
    """
    Devuelve los últimos N mensajes del agente como contexto para el prompt.
    Incluye mensajes de la sesión actual y, si hay pocos, de sesiones anteriores
    del mismo agente — así la memoria persiste entre reinicios de la app.
    """
    try:
        _asegurar_tablas()
        with get_session() as s:
            # Sesión actual primero
            actuales = (
                s.query(Mensaje)
                .filter(Mensaje.agente_id == agente_id,
                        Mensaje.sesion_id == sesion_id)
                .order_by(Mensaje.ts.desc())
                .limit(n_mensajes)
                .all()
            )
            msgs = list(reversed(actuales))

            # Si hay pocos mensajes en esta sesión, completar con historial anterior
            if len(msgs) < 4:
                faltan = n_mensajes - len(msgs)
                previos = (
                    s.query(Mensaje)
                    .filter(Mensaje.agente_id == agente_id,
                            Mensaje.sesion_id != sesion_id)
                    .order_by(Mensaje.ts.desc())
                    .limit(faltan)
                    .all()
                )
                if previos:
                    msgs = list(reversed(previos)) + msgs

        if not msgs:
            return ""

        lineas = ["--- Historial de conversación reciente ---"]
        for m in msgs:
            prefijo = "Usuario" if m.rol == "usuario" else "Tú (respuesta anterior)"
            lineas.append(f"{prefijo}: {m.contenido[:300]}")
        lineas.append("--- Fin del historial ---")
        return "\n".join(lineas)
    except Exception:
        return ""


def get_historial_sesion(agente_id: str, sesion_id: str) -> list[dict]:
    """Devuelve todos los mensajes de una sesión."""
    try:
        _asegurar_tablas()
        with get_session() as s:
            msgs = (
                s.query(Mensaje)
                .filter(
                    Mensaje.agente_id == agente_id,
                    Mensaje.sesion_id == sesion_id,
                )
                .order_by(Mensaje.ts.asc())
                .all()
            )
        return [m.to_dict() for m in msgs]
    except Exception:
        return []


def get_sesiones_agente(agente_id: str, limit: int = 20) -> list[dict]:
    """Lista las últimas sesiones de un agente."""
    try:
        _asegurar_tablas()
        with get_session() as s:
            convs = (
                s.query(Conversacion)
                .filter(Conversacion.agente_id == agente_id)
                .order_by(Conversacion.ts_ultimo.desc())
                .limit(limit)
                .all()
            )
        return [{
            "sesion_id": c.sesion_id,
            "ts_inicio": c.ts_inicio.isoformat() if c.ts_inicio else None,
            "ts_ultimo": c.ts_ultimo.isoformat() if c.ts_ultimo else None,
        } for c in convs]
    except Exception:
        return []


def limpiar_sesion(agente_id: str, sesion_id: str) -> None:
    """Elimina todos los mensajes de una sesión."""
    try:
        _asegurar_tablas()
        with get_session() as s:
            s.query(Mensaje).filter(
                Mensaje.agente_id == agente_id,
                Mensaje.sesion_id == sesion_id,
            ).delete()
            s.query(Conversacion).filter(
                Conversacion.agente_id == agente_id,
                Conversacion.sesion_id == sesion_id,
            ).delete()
            s.commit()
    except Exception:
        pass
