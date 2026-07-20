"""
core/database.py — Capa de persistencia con SQLAlchemy (modo dual, ADR-0005/0013).

Motores:
  SQLite (defecto)  — desarrollo y escritorio mono-usuario, zero-config
                      (WAL habilitado).
  PostgreSQL        — planta con alta telemetría/concurrencia, activado con
                      AGENTDESK_DB_URL=postgresql+psycopg2://user:pass@host/db

Esquema (ADR-0013): gobernado por Alembic (migrations/), no por
Base.metadata.create_all() ciego — cambios reproducibles e incrementales
entre el instalador de escritorio y una base de producción. create_all()
sigue como respaldo best-effort si Alembic no está disponible.

Tablas:
  ejecuciones      — historial de tareas ejecutadas por agente
  monitor_fuentes  — fuentes web configuradas para monitorear
  monitor_datos    — datos históricos recolectados por el monitor
  monitor_alertas  — alertas generadas por cambios significativos
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re as _re
from datetime import datetime
from pathlib import Path
from sqlalchemy import (
    create_engine, Column, String, Integer, Float,
    DateTime, Boolean, Text, event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


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


class RefreshToken(Base):
    """
    Refresh token rotativo (ADR-0008). Se almacena SOLO el hash SHA-256 del
    token (nunca el valor); cada uso lo revoca y emite uno nuevo (rotación).
    El reuso de un token revocado delata robo y revoca toda la familia.
    """
    __tablename__ = "refresh_tokens"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    token_hash  = Column(String(64), nullable=False, unique=True, index=True)
    username    = Column(String(64), nullable=False, index=True)
    expira      = Column(DateTime, nullable=False)
    revocado    = Column(Boolean, default=False)
    ts_creacion = Column(DateTime, default=datetime.utcnow)


class AuditoriaIA(Base):
    """
    Traza forense de CADA interacción de agente (ADR-0007): prompt, contexto,
    modelo, herramientas, veredicto de guardrails y respuesta, con timestamp.
    Auditoría para sectores regulados — portable SQLite/PostgreSQL (ADR-0005).
    """
    __tablename__ = "auditoria_ia"
    id                 = Column(Integer, primary_key=True, autoincrement=True)
    ts                 = Column(DateTime, default=datetime.utcnow, index=True)
    user_id            = Column(String(64),  index=True, default="anonimo")
    agente_id          = Column(String(64),  index=True)
    tipo               = Column(String(24))               # chat | tarea | chat_stream
    proveedor          = Column(String(24))               # groq/gemini/... (si aplica)
    modelo             = Column(String(96))
    prompt             = Column(Text)                     # entrada (truncada)
    contexto           = Column(Text)                     # sesion/archivo/tarea
    contexto_hats      = Column(Text)                     # memoria HATs inyectada (ADR-0014)
    respuesta          = Column(Text)                     # salida (truncada)
    herramientas_json  = Column(Text, default="[]")       # tools invocadas
    costo_estimado     = Column(Integer, default=0)       # tokens (exactos o aprox len/4)
    tokens_exactos     = Column(Boolean, default=False)   # True = del proveedor, no estimado (ADR-0017)
    costo_usd_estimado = Column(Float, default=0.0)       # FinOps: tarifa aprox por proveedor (ADR-0017)
    veredicto_guardrail = Column(String(32), default="no_aplica")
    guardrails_json    = Column(Text, default="[]")       # veredicto de CADA guardrail (ADR-0014)
    duracion_s         = Column(Float)
    exitoso            = Column(Boolean, default=True)

    def to_dict(self) -> dict:
        return {
            "id":                  self.id,
            "ts":                  self.ts.isoformat() if self.ts else None,
            "user_id":             self.user_id,
            "agente_id":           self.agente_id,
            "tipo":                self.tipo,
            "proveedor":           self.proveedor,
            "modelo":              self.modelo,
            "prompt":              self.prompt,
            "contexto":            self.contexto,
            "contexto_hats":       self.contexto_hats or "",
            "respuesta":           self.respuesta,
            "herramientas":        json.loads(self.herramientas_json or "[]"),
            "costo_estimado":      self.costo_estimado,
            "tokens_exactos":      bool(self.tokens_exactos),
            "costo_usd_estimado":  self.costo_usd_estimado or 0.0,
            "veredicto_guardrail": self.veredicto_guardrail,
            "guardrails":          json.loads(self.guardrails_json or "[]"),
            "duracion_s":          self.duracion_s,
            "exitoso":             self.exitoso,
        }


# ── Inicialización ────────────────────────────────────────────────────────────

_engine  = None
_Session = None


def _url_sin_credenciales(url: str) -> str:
    """Oculta user:pass de la URL para poder loggearla con seguridad."""
    return _re.sub(r"//[^@/]+@", "//***@", url)


def _verificar_conexion_async(db_url: str) -> None:
    """
    Chequeo rápido de alcanzabilidad con asyncpg (ADR-0013), antes de armar
    el engine síncrono: falla temprano con un mensaje claro si el servidor
    Postgres no responde, en vez de que el primer INSERT bloqueante se
    cuelgue con un traceback confuso.

    No reemplaza la capa ORM (que sigue en psycopg2 síncrono, ADR-0005) —
    es una verificación de arranque puntual, best-effort si asyncpg no está
    instalado (dependencia opcional de planta).
    """
    if "postgresql" not in db_url:
        return
    try:
        import asyncpg
    except ImportError:
        logging.getLogger(__name__).warning(
            "asyncpg no instalado — se omite la verificación rápida de conexión "
            "(el engine síncrono psycopg2 igual intentará conectar)."
        )
        return

    # asyncpg no entiende el sufijo +psycopg2/+asyncpg del driver — solo el DSN base
    dsn = _re.sub(r"^postgresql\+\w+://", "postgresql://", db_url)

    async def _probar() -> None:
        conn = await asyncpg.connect(dsn, timeout=5)
        await conn.close()

    try:
        asyncio.run(_probar())
    except Exception as exc:
        raise ConnectionError(
            f"No se pudo conectar a PostgreSQL ({_url_sin_credenciales(db_url)}): {exc}"
        ) from exc


# Primera revision Alembic del proyecto (Fase 15, ADR-0013). Constante
# unica: si una DB legada (tablas creadas por create_all() ANTES de que
# Alembic existiera, sin alembic_version sellada) se detecta, se sella
# como si esta revision ya estuviera aplicada -- sus tablas YA existen,
# volver a crearlas fallaria con "table already exists".
_REVISION_BASELINE = "c403b23afae5"


def _sellar_db_legada_si_corresponde(cfg) -> None:
    """
    2026-07-20, hallazgo real: una DB creada por una version vieja de la
    app (create_all() ciego, antes de que Alembic entrara al proyecto)
    tiene las tablas del baseline pero CERO alembic_version. 'upgrade
    head' fallaba siempre con "table already exists" al intentar recrear
    ese baseline -- degradando a create_all() de respaldo EN CADA
    arranque, para siempre. create_all() no ALTERA tablas existentes, asi
    que columnas de migraciones posteriores (ej. auditoria_ia.
    contexto_hats) nunca llegaban: el HAT de memoria fallaba en silencio
    en cada consulta.

    Deteccion: sin ninguna revision aplicada, pero con una tabla del
    baseline ya presente -> es legada, no nueva. Se sella el baseline UNA
    vez; el upgrade real (con las columnas nuevas) sigue su curso normal.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic import command
    from sqlalchemy import inspect

    with _engine.connect() as conn:
        version_actual = MigrationContext.configure(conn).get_current_heads()
    if version_actual:
        return   # ya sellada (nueva o migrada antes) -- nada que hacer

    if "auditoria_ia" in inspect(_engine).get_table_names():
        logger = logging.getLogger(__name__)
        logger.warning(
            "Alembic: DB legada sin sellar detectada (tablas existen, "
            "alembic_version ausente) — sellando baseline %s antes de migrar",
            _REVISION_BASELINE,
        )
        command.stamp(cfg, _REVISION_BASELINE)


def _aplicar_migraciones(db_url_efectiva: str) -> None:
    """
    Corre `alembic upgrade head` contra el motor activo (ADR-0013): el
    esquema se crea/actualiza de forma reproducible e incremental en vez de
    un create_all() ciego — funciona igual para SQLite y PostgreSQL.

    Best-effort con respaldo: si Alembic no está disponible (no instalado,
    o migrations/ no empaquetada en el build de escritorio), degrada a
    Base.metadata.create_all() con un aviso — nunca bloquea el arranque.
    """
    _logger = logging.getLogger(__name__)
    try:
        from alembic import command
        from alembic.config import Config

        raiz     = Path(__file__).resolve().parent.parent
        ini_path = raiz / "alembic.ini"
        if not ini_path.is_file():
            raise FileNotFoundError(f"alembic.ini no encontrado en {ini_path}")

        os.environ["AGENTDESK_ALEMBIC_DB_URL"] = db_url_efectiva
        try:
            cfg = Config(str(ini_path))
            cfg.set_main_option("script_location", str(raiz / "migrations"))
            _sellar_db_legada_si_corresponde(cfg)
            command.upgrade(cfg, "head")
        finally:
            os.environ.pop("AGENTDESK_ALEMBIC_DB_URL", None)

        _logger.info("Alembic: esquema actualizado a head (%s)",
                     _url_sin_credenciales(db_url_efectiva))
    except Exception as exc:
        _logger.warning("Alembic no disponible/fallo (%s) — usando create_all() de respaldo.", exc)
        Base.metadata.create_all(_engine)


def init_db(db_path: str | Path | None = None) -> None:
    """
    Inicializa la base de datos (modo dual, ADR-0005/0013).

    - Con AGENTDESK_DB_URL definida (y sin db_path explícito) usa ese motor:
      PostgreSQL para planta (pool con pre-ping ante redes inestables, y
      chequeo async previo de conectividad), o cualquier URL de SQLAlchemy
      — incluida sqlite:/// para pruebas.
    - Sin la variable: SQLite local en el data dir (comportamiento histórico,
      zero-config).
    - El esquema lo gobierna Alembic (migrations/), no create_all() directo.
    """
    global _engine, _Session
    _logger = logging.getLogger(__name__)

    db_url = os.environ.get("AGENTDESK_DB_URL", "").strip() if db_path is None else ""

    if db_url and not db_url.startswith("sqlite"):
        # ── Motor industrial (PostgreSQL u otro servidor) ─────────────────
        _verificar_conexion_async(db_url)
        _engine = create_engine(
            db_url,
            pool_pre_ping=True,    # detecta conexiones muertas (red de planta)
            pool_size=10,          # 10+ estaciones concurrentes
            max_overflow=20,
        )
        db_url_efectiva = db_url
        _logger.info("DB industrial conectada: %s", _url_sin_credenciales(db_url))
    else:
        # ── SQLite (defecto escritorio, o URL sqlite:/// de AGENTDESK_DB_URL) ─
        if db_url.startswith("sqlite"):
            ruta = db_url.split("///", 1)[-1]
            db_path = Path(ruta) if ruta and ruta != ":memory:" else None
        if db_path is None:
            from core.path_manager import data_path
            db_path = data_path("") / "agentdesk.db"

        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_url_efectiva = f"sqlite:///{db_path}"

        # Fase 18 (ADR-0016), hallazgo real: StaticPool comparte UN SOLO
        # objeto sqlite3.Connection entre TODOS los hilos. Bajo escritura
        # concurrente real (tests/stress/test_db_concurrency.py) eso corrompe
        # el estado del cursor entre hilos ("sqlite3.InterfaceError: bad
        # parameter or other API misuse") -- no es un problema de locking,
        # es reuso inseguro del mismo objeto Python desde varios hilos a la
        # vez. Esta base es siempre un archivo real (nunca ":memory:", que
        # ni siquiera esta soportado hoy -- ver el fallback a db_path=None
        # arriba), asi que no hace falta compartir una conexion: el pool por
        # defecto de SQLAlchemy le da a cada sesion su propia conexion real
        # al mismo archivo, y SQLite coordina la concurrencia a nivel de
        # archivo (WAL + busy_timeout), que es el mecanismo probado para esto.
        _engine = create_engine(
            db_url_efectiva,
            connect_args={"check_same_thread": False},
        )

        # Habilitar WAL mode para mejor concurrencia. busy_timeout: SQLite
        # reporta "database is locked" DE INMEDIATO por defecto (timeout 0)
        # cuando otra conexion ya tiene el lock de escritura -- con varios
        # agentes escribiendo a la vez eso perdia escrituras reales en vez
        # de esperar el turno. busy_timeout hace que cada conexion reintente
        # hasta 5s antes de fallar, absorbiendo la contencion normal de N
        # agentes escribiendo casi al mismo tiempo sin perder datos.
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(conn, _):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")

    _aplicar_migraciones(db_url_efectiva)
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
