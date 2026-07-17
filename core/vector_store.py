"""
core/vector_store.py — Memoria Hermes: vector store local persistente
(Fase 25, ADR-0023).

Reemplaza la memoria efimera del ContextHarness (TF-IDF recalculado en
cada consulta sobre auditoria_ia) por una base vectorial PERSISTENTE en
%APPDATA% (SQLite propio, separado de la DB principal). Se descarto
ChromaDB adrede: arrastra onnxruntime y un arbol de dependencias que es
exactamente la clase de fallo invisible-a-PyInstaller de la Fase 22 —
este store es SQLite (stdlib) + criptografia de similitud en Python puro.

Embeddings (2 niveles, degradacion honesta):
  - `hash-v1` (defecto): feature hashing 256-dim L2-normalizado, puro
    Python, determinista, offline. Similitud LEXICA robusta.
  - `ollama` (opcional): si AGENTDESK_OLLAMA_EMBED esta definida (modelo,
    p.ej. "nomic-embed-text") y el Ollama local responde, embeddings
    densos reales — similitud SEMANTICA profunda. Un store puede mezclar
    modelos: la busqueda solo compara vectores del MISMO modelo.

[SEMANTIC-PRIVACY] (ADR-0023): guardar() y buscar() EXIGEN user_id y
proyecto_id — sin ambos, ValueError (fail-closed, nunca degradan a "todos
los usuarios/proyectos"). El aislamiento se aplica en el WHERE de SQL, no
filtrando en Python despues de leer.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import struct
import threading
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

DIM_HASH = 256
PROYECTO_GLOBAL = "global"   # ambito por defecto para memoria sin proyecto

_TOKEN_RE = re.compile(r"[a-záéíóúñü0-9_]+", re.I)

# Palabras funcionales que solo generan similitud espuria entre textos no
# relacionados (mismo problema que el TF-IDF con corpus pequenos, ADR-0009).
_STOPWORDS = frozenset(
    "el la los las un una unos unas de del al a en y o u que se su sus es "
    "son para por con sin como cual cuales cuando donde quien cuanto esta "
    "este esto estos estas hay fue ser mas pero si no lo le les mi tu nos "
    "the a an of to in and or is are for with".split()
)


# ── Embeddings ─────────────────────────────────────────────────────────────────

def vectorizar_hash(texto: str, dim: int = DIM_HASH) -> list[float]:
    """
    Feature hashing determinista (puro Python, offline): cada token suma
    +/-1 en el bucket sha256(token) % dim; L2-normalizado. Mismo texto =
    mismo vector SIEMPRE — apto para persistir y comparar entre sesiones.
    """
    vec = [0.0] * dim
    for token in _TOKEN_RE.findall((texto or "").lower()):
        if token in _STOPWORDS:
            continue
        h = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(h[:4], "big") % dim
        signo = 1.0 if h[4] % 2 == 0 else -1.0
        vec[bucket] += signo
    norma = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norma for v in vec]


def _vectorizar_ollama(texto: str) -> tuple[list[float], str] | None:
    """Embedding denso via Ollama local (best-effort; None si no disponible)."""
    modelo = os.environ.get("AGENTDESK_OLLAMA_EMBED", "").strip()
    if not modelo:
        return None
    try:
        import urllib.request
        host = os.environ.get("AGENTDESK_OLLAMA_HOST", "http://127.0.0.1:11434")
        if not host.lower().startswith(("http://", "https://")):
            return None
        req = urllib.request.Request(
            f"{host}/api/embeddings",
            data=json.dumps({"model": modelo, "prompt": texto}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 - host local configurado
            emb = json.loads(resp.read()).get("embedding")
        if emb:
            norma = math.sqrt(sum(v * v for v in emb)) or 1.0
            return [v / norma for v in emb], f"ollama:{modelo}"
    except Exception as exc:
        logger.debug("Hermes: Ollama embeddings no disponible (%s)", exc)
    return None


def vectorizar(texto: str) -> tuple[list[float], str]:
    """Retorna (vector, modelo). Ollama denso si esta; hashing si no."""
    denso = _vectorizar_ollama(texto)
    if denso is not None:
        return denso
    return vectorizar_hash(texto), "hash-v1"


def _serializar(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _deserializar(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


# ── Store persistente ──────────────────────────────────────────────────────────

class VectorStoreHermes:
    """
    Vector store SQLite de un solo archivo. Thread-safe (lock propio +
    conexion por operacion, WAL). Escrituras best-effort: la memoria nunca
    debe romper la interaccion que la alimenta (mismo principio que
    audit_service, ADR-0007).
    """

    def __init__(self, ruta: str | Path | None = None) -> None:
        if ruta is None:
            from core.path_manager import data_path
            ruta = data_path("db/memoria_vectorial.db")
        self._ruta = str(ruta)
        self._lock = threading.Lock()
        self._crear_esquema()

    @contextmanager
    def _conn(self):
        # sqlite3: el context manager nativo solo maneja la TRANSACCION,
        # no cierra la conexion — aqui se garantizan commit y close.
        c = sqlite3.connect(self._ruta, timeout=10)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            yield c
            c.commit()
        finally:
            c.close()

    def _crear_esquema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS memoria_vectorial (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT NOT NULL,
                    proyecto_id TEXT NOT NULL,
                    agente_id   TEXT NOT NULL DEFAULT '',
                    tipo        TEXT NOT NULL DEFAULT 'interaccion',
                    texto       TEXT NOT NULL,
                    embedding   BLOB NOT NULL,
                    modelo      TEXT NOT NULL,
                    ts          REAL NOT NULL
                )
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS ix_memoria_scope
                ON memoria_vectorial (user_id, proyecto_id, agente_id)
            """)

    @staticmethod
    def _exigir_scope(user_id: str, proyecto_id: str) -> None:
        # [SEMANTIC-PRIVACY]: fail-closed — sin scope completo no hay memoria.
        if not user_id or not str(user_id).strip():
            raise ValueError("Hermes: user_id obligatorio (SEMANTIC-PRIVACY)")
        if not proyecto_id or not str(proyecto_id).strip():
            raise ValueError("Hermes: proyecto_id obligatorio (SEMANTIC-PRIVACY)")

    def guardar(self, texto: str, *, user_id: str, proyecto_id: str,
                agente_id: str = "", tipo: str = "interaccion",
                ts: float | None = None) -> int | None:
        """Vectoriza y persiste. Retorna el id, o None si fallo (best-effort)."""
        self._exigir_scope(user_id, proyecto_id)
        if not texto or not texto.strip():
            return None
        try:
            vec, modelo = vectorizar(texto)
            with self._lock, self._conn() as c:
                cur = c.execute(
                    "INSERT INTO memoria_vectorial "
                    "(user_id, proyecto_id, agente_id, tipo, texto, embedding, modelo, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, proyecto_id, agente_id, tipo, texto[:4000],
                     _serializar(vec), modelo, ts if ts is not None else time.time()),
                )
                return cur.lastrowid
        except ValueError:
            raise
        except Exception as exc:
            logger.warning("Hermes: guardar fallo (%s) — memoria omitida", exc)
            return None

    def buscar(self, query: str, *, user_id: str, proyecto_id: str,
               agente_id: str | None = None, tipo: str | None = None,
               top_k: int = 5, umbral: float = 0.05) -> list[dict]:
        """
        Similitud coseno dentro del scope (user_id, proyecto_id[, agente_id]).
        Solo compara vectores del mismo modelo de embedding que la query.
        Retorna [{texto, similitud, ts, tipo, agente_id, id}] descendente.
        """
        self._exigir_scope(user_id, proyecto_id)
        if not query or not query.strip():
            return []
        try:
            vec_q, modelo_q = vectorizar(query)
            sql = ("SELECT id, agente_id, tipo, texto, embedding, ts "
                   "FROM memoria_vectorial "
                   "WHERE user_id = ? AND proyecto_id = ? AND modelo = ?")
            params: list = [user_id, proyecto_id, modelo_q]
            if agente_id:
                sql += " AND agente_id = ?"
                params.append(agente_id)
            if tipo:
                sql += " AND tipo = ?"
                params.append(tipo)
            with self._lock, self._conn() as c:
                filas = c.execute(sql, params).fetchall()

            resultados = []
            for fid, faid, ftipo, texto, blob, ts in filas:
                vec = _deserializar(blob)
                if len(vec) != len(vec_q):
                    continue
                sim = sum(a * b for a, b in zip(vec_q, vec))
                if sim >= umbral:
                    resultados.append({"id": fid, "agente_id": faid, "tipo": ftipo,
                                       "texto": texto, "similitud": sim, "ts": ts})
            resultados.sort(key=lambda r: r["similitud"], reverse=True)
            # Corte RELATIVO al mejor match (mismo criterio que el TF-IDF
            # de ADR-0009): con textos cortos, un recuerdo no relacionado
            # puede superar el umbral absoluto solo por vocabulario comun.
            if resultados:
                corte = max(umbral, resultados[0]["similitud"] * 0.45)
                resultados = [r for r in resultados if r["similitud"] >= corte]
            return resultados[:max(1, top_k)]
        except ValueError:
            raise
        except Exception as exc:
            logger.warning("Hermes: buscar fallo (%s) — sin memoria esta vez", exc)
            return []

    def contar(self, *, user_id: str, proyecto_id: str) -> int:
        self._exigir_scope(user_id, proyecto_id)
        with self._lock, self._conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM memoria_vectorial "
                "WHERE user_id = ? AND proyecto_id = ?",
                (user_id, proyecto_id),
            ).fetchone()[0]


_instancia: VectorStoreHermes | None = None
_instancia_lock = threading.Lock()


def hermes() -> VectorStoreHermes:
    """Singleton del store en la ruta por defecto (%APPDATA%)."""
    global _instancia
    with _instancia_lock:
        if _instancia is None:
            _instancia = VectorStoreHermes()
        return _instancia
