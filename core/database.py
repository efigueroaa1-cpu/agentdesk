"""
core/database.py — Base de datos SQLite con SQLAlchemy.

Tablas:
  ejecuciones      — historial de tareas ejecutadas por agente
  monitor_fuentes  — fuentes web configuradas para monitorear
  monitor_datos    — datos históricos recolectados por el monitor
  monitor_alertas  — alertas generadas por cambios significativos
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from sqlalchemy import (
    create_engine, Column, String, Integer, Float,
    DateTime, Boolean, Text, event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


# ── Modelos ───────────────────────────────────────────────────────────────────

class Ejecucion(Base):
    """Historial de cada tarea ejecutada por un agente."""
    __tablename__ = "ejecuciones"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    agente_id   = Column(String(64), nullable=False, index=True)
    agente_nombre = Column(String(128))
    tarea       = Column(String(256))
    exitoso     = Column(Boolean, default=True)
    duracion_s  = Column(Float)
    resumen     = Column(Text)
    kpis_json   = Column(Text)          # JSON serializado
    archivo_id  = Column(String(32))    # si usó un archivo
    ts          = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id":       self.id,
            "agente_id":    self.agente_id,
            "agente_nombre":self.agente_nombre,
            "tarea":    self.tarea,
            "exitoso":  self.exitoso,
            "duracion_s":   self.duracion_s,
            "resumen":  self.resumen,
            "kpis":     json.loads(self.kpis_json or "{}"),
            "ts":       self.ts.isoformat() if self.ts else None,
        }


class MonitorFuente(Base):
    """Fuente web configurada para monitorear periódicamente."""
    __tablename__ = "monitor_fuentes"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    nombre      = Column(String(128), nullable=False)
    categoria   = Column(String(64))       # futbol, energia, finanzas, etc.
    tipo        = Column(String(32))       # api_json, scraping, rss
    url         = Column(String(512), nullable=False)
    parametros  = Column(Text)             # JSON con params adicionales
    intervalo_min = Column(Integer, default=60)  # cada cuántos minutos
    activo      = Column(Boolean, default=True)
    ultima_fetch = Column(DateTime)
    ts_creacion = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":       self.id,
            "nombre":   self.nombre,
            "categoria":self.categoria,
            "tipo":     self.tipo,
            "url":      self.url,
            "parametros": json.loads(self.parametros or "{}"),
            "intervalo_min": self.intervalo_min,
            "activo":   self.activo,
            "ultima_fetch": self.ultima_fetch.isoformat() if self.ultima_fetch else None,
        }


class MonitorDato(Base):
    """Dato individual recolectado por el monitor en cada ciclo."""
    __tablename__ = "monitor_datos"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    fuente_id   = Column(Integer, nullable=False, index=True)
    fuente_nombre = Column(String(128))
    categoria   = Column(String(64), index=True)
    clave       = Column(String(256), index=True)   # p.ej. "Colo-Colo/victorias"
    valor       = Column(Text)
    valor_numerico = Column(Float)
    unidad      = Column(String(32))
    metadata_json = Column(Text)         # JSON con datos adicionales
    ts          = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id":       self.id,
            "fuente_id":    self.fuente_id,
            "fuente_nombre":self.fuente_nombre,
            "categoria":self.categoria,
            "clave":    self.clave,
            "valor":    self.valor,
            "valor_numerico": self.valor_numerico,
            "unidad":   self.unidad,
            "metadata": json.loads(self.metadata_json or "{}"),
            "ts":       self.ts.isoformat() if self.ts else None,
        }


class MonitorAlerta(Base):
    """Alerta generada cuando se detecta un cambio significativo."""
    __tablename__ = "monitor_alertas"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    fuente_id   = Column(Integer, index=True)
    fuente_nombre = Column(String(128))
    titulo      = Column(String(256))
    descripcion = Column(Text)
    nivel       = Column(String(16), default="info")  # info, warn, critico
    leida       = Column(Boolean, default=False)
    ts          = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id":          self.id,
            "fuente_nombre": self.fuente_nombre,
            "titulo":      self.titulo,
            "descripcion": self.descripcion,
            "nivel":       self.nivel,
            "leida":       self.leida,
            "ts":          self.ts.isoformat() if self.ts else None,
        }


class Usuario(Base):
    """
    Usuario del sistema con rol RBAC.

    Roles:
      admin      — control total (gestión de usuarios, kill switch, config)
      supervisor — ejecución de agentes, lectura de reportes y compliance
      viewer     — solo lectura (dashboards, historial, métricas)

    La contraseña se almacena SOLO como hash bcrypt. Nunca texto plano.
    """
    __tablename__ = "usuarios"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    username         = Column(String(64),  nullable=False, unique=True, index=True)
    password_hash    = Column(String(256), nullable=False)
    rol              = Column(String(16),  nullable=False, default="viewer")
    activo           = Column(Boolean, default=True)
    ts_creacion      = Column(DateTime, default=datetime.utcnow)
    ultimo_acceso    = Column(DateTime)

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "username":      self.username,
            "rol":           self.rol,
            "activo":        self.activo,
            "ts_creacion":   self.ts_creacion.isoformat() if self.ts_creacion else None,
            "ultimo_acceso": self.ultimo_acceso.isoformat() if self.ultimo_acceso else None,
        }


class GuardrailEvento(Base):
    """Evento de abort de un guardrail. Alimenta el motor de Compliance."""
    __tablename__ = "guardrail_eventos"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    agente_id  = Column(String(64), nullable=False, index=True)
    guardrail  = Column(String(64), nullable=False, index=True)
    motivo     = Column(Text)
    ts         = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "agente_id": self.agente_id,
            "guardrail": self.guardrail,
            "motivo":    self.motivo or "",
            "ts":        self.ts.isoformat() if self.ts else None,
        }


class GanttTask(Base):
    """Tarea del cronograma Gantt con soporte CPM (Ruta Crítica)."""
    __tablename__ = "gantt_tasks"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    proyecto_id      = Column(String(64), nullable=False, index=True)
    nombre           = Column(String(256), nullable=False)
    agente_id        = Column(String(64), index=True)
    inicio_plan      = Column(DateTime, nullable=False)
    fin_plan         = Column(DateTime, nullable=False)
    duracion_dias    = Column(Float, nullable=False)
    inicio_real      = Column(DateTime)
    fin_real         = Column(DateTime)
    pct_completado   = Column(Float, default=0.0)
    # CPM — rellenos por el motor después de calcular la ruta crítica
    es               = Column(DateTime)             # Early Start
    ef               = Column(DateTime)             # Early Finish
    ls               = Column(DateTime)             # Late Start
    lf               = Column(DateTime)             # Late Finish
    holgura_dias     = Column(Float, default=0.0)
    en_ruta_critica  = Column(Boolean, default=False)
    dependencias_json = Column(Text, default="[]")  # [id, id, ...]
    color            = Column(String(16), default="#00d4ff")
    ts               = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json
        def _dt(v): return v.isoformat() if v else None
        return {
            "id":             self.id,
            "proyecto_id":    self.proyecto_id,
            "nombre":         self.nombre,
            "agente_id":      self.agente_id or "",
            "inicio_plan":    _dt(self.inicio_plan),
            "fin_plan":       _dt(self.fin_plan),
            "duracion_dias":  self.duracion_dias,
            "inicio_real":    _dt(self.inicio_real),
            "fin_real":       _dt(self.fin_real),
            "pct_completado": self.pct_completado or 0.0,
            "es":             _dt(self.es),
            "ef":             _dt(self.ef),
            "ls":             _dt(self.ls),
            "lf":             _dt(self.lf),
            "holgura_dias":   self.holgura_dias or 0.0,
            "en_ruta_critica": bool(self.en_ruta_critica),
            "dependencias":   _json.loads(self.dependencias_json or "[]"),
            "color":          self.color or "#00d4ff",
            "ts":             _dt(self.ts),
        }


class AnalisisFinanciero(Base):
    """Snapshot de análisis financiero de un agente con indicadores macro Chile."""
    __tablename__ = "analisis_financiero"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    agente_id        = Column(String(64), nullable=False, index=True)
    indicadores_json = Column(Text)   # IndicadorChile serializado
    presupuesto_json = Column(Text)   # PresupuestoConfig serializado
    flujo_json       = Column(Text)   # lista de FlujoCajaProyeccion
    uf_valor         = Column(Float)  # desnormalizado para queries rápidas
    dolar_valor      = Column(Float)
    flujo_neto       = Column(Float)
    ts               = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "agente_id":   self.agente_id,
            "indicadores": json.loads(self.indicadores_json or "{}"),
            "presupuesto": json.loads(self.presupuesto_json or "{}"),
            "flujo":       json.loads(self.flujo_json or "[]"),
            "uf_valor":    self.uf_valor,
            "dolar_valor": self.dolar_valor,
            "flujo_neto":  self.flujo_neto,
            "ts":          self.ts.isoformat() if self.ts else None,
        }


# ── Inicialización ────────────────────────────────────────────────────────────

_engine  = None
_Session = None


def init_db(db_path: str | Path | None = None) -> None:
    """Inicializa la base de datos. Se llama una vez al arrancar."""
    global _engine, _Session
    from core.path_manager import data_path

    if db_path is None:
        db_path = data_path("") / "agentdesk.db"

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Habilitar WAL mode para mejor concurrencia
    @event.listens_for(_engine, "connect")
    def set_sqlite_pragma(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)


def get_session() -> Session:
    if _Session is None:
        init_db()
    return _Session()


# ── DAO helpers ───────────────────────────────────────────────────────────────

def guardar_ejecucion(
    agente_id: str, agente_nombre: str, tarea: str,
    exitoso: bool, duracion_s: float | None = None,
    resumen: str = "", kpis: dict | None = None,
    archivo_id: str | None = None,
) -> int:
    with get_session() as s:
        e = Ejecucion(
            agente_id=agente_id, agente_nombre=agente_nombre,
            tarea=tarea, exitoso=exitoso, duracion_s=duracion_s,
            resumen=resumen[:1000] if resumen else "",
            kpis_json=json.dumps(kpis or {}, ensure_ascii=False),
            archivo_id=archivo_id,
        )
        s.add(e); s.commit()
        return e.id


def get_historial(agente_id: str | None = None, limit: int = 50) -> list[dict]:
    with get_session() as s:
        q = s.query(Ejecucion).order_by(Ejecucion.ts.desc())
        if agente_id:
            q = q.filter(Ejecucion.agente_id == agente_id)
        return [r.to_dict() for r in q.limit(limit).all()]


def get_stats_agente(agente_id: str) -> dict:
    with get_session() as s:
        rows = s.query(Ejecucion).filter(Ejecucion.agente_id == agente_id).all()
        if not rows:
            return {"total":0,"ok":0,"fail":0,"tasa_exito":None,"latencia_prom":None}
        ok   = sum(1 for r in rows if r.exitoso)
        lats = [r.duracion_s for r in rows if r.duracion_s]
        return {
            "total":       len(rows),
            "ok":          ok,
            "fail":        len(rows)-ok,
            "tasa_exito":  round(ok/len(rows)*100,1),
            "latencia_prom": round(sum(lats)/len(lats),3) if lats else None,
            "ultima_ts":   rows[0].ts.isoformat() if rows else None,
        }


def guardar_dato_monitor(
    fuente_id: int, fuente_nombre: str, categoria: str,
    clave: str, valor: str, valor_numerico: float | None = None,
    unidad: str = "", metadata: dict | None = None,
) -> None:
    with get_session() as s:
        s.add(MonitorDato(
            fuente_id=fuente_id, fuente_nombre=fuente_nombre,
            categoria=categoria, clave=clave, valor=str(valor)[:500],
            valor_numerico=valor_numerico, unidad=unidad,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        ))
        s.commit()


def get_datos_monitor(
    categoria: str | None = None,
    clave: str | None = None,
    fuente_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    with get_session() as s:
        q = s.query(MonitorDato).order_by(MonitorDato.ts.desc())
        if categoria: q = q.filter(MonitorDato.categoria == categoria)
        if clave:     q = q.filter(MonitorDato.clave.like(f"%{clave}%"))
        if fuente_id: q = q.filter(MonitorDato.fuente_id == fuente_id)
        return [r.to_dict() for r in q.limit(limit).all()]


def guardar_alerta(
    fuente_id: int, fuente_nombre: str,
    titulo: str, descripcion: str, nivel: str = "info",
) -> None:
    with get_session() as s:
        s.add(MonitorAlerta(
            fuente_id=fuente_id, fuente_nombre=fuente_nombre,
            titulo=titulo, descripcion=descripcion, nivel=nivel,
        ))
        s.commit()


def get_alertas(solo_no_leidas: bool = False, limit: int = 50) -> list[dict]:
    with get_session() as s:
        q = s.query(MonitorAlerta).order_by(MonitorAlerta.ts.desc())
        if solo_no_leidas: q = q.filter(MonitorAlerta.leida == False)
        return [r.to_dict() for r in q.limit(limit).all()]


def marcar_alertas_leidas() -> None:
    with get_session() as s:
        s.query(MonitorAlerta).filter(MonitorAlerta.leida == False)\
            .update({"leida": True})
        s.commit()
