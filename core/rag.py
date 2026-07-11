"""
core/rag.py — RAG (Retrieval-Augmented Generation) en Python puro.

Problema que resuelve:
  ANTES: el agente recibe el CSV completo (14 KB, 200 filas) y lo lee todo
  AHORA: divide en chunks, encuentra los más relevantes para la pregunta,
         y solo envía esos chunks al agente → respuestas más precisas

Sin dependencias externas:
  - TF-IDF para vectorizar texto (Python puro)
  - Similitud coseno para encontrar chunks relevantes
  - Chunk overlap para no perder contexto

Soporte de formatos:
  - CSV/TSV
  - JSON
  - Texto plano / Markdown
  - (Experimental) PDF texto
"""
from __future__ import annotations
import math
import re
import logging

logger = logging.getLogger(__name__)

CHUNK_SIZE    = 400    # tokens aprox por chunk
CHUNK_OVERLAP = 80     # tokens de solapamiento
TOP_K         = 5      # chunks más relevantes a recuperar
MAX_CHARS     = 8000   # máximo de caracteres a enviar al agente


# ── Chunking ──────────────────────────────────────────────────────────────────

def _split_texto(texto: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Divide texto en chunks solapados."""
    palabras = texto.split()
    if len(palabras) <= chunk_size:
        return [texto]
    chunks = []
    i = 0
    while i < len(palabras):
        fin    = min(i + chunk_size, len(palabras))
        chunk  = " ".join(palabras[i:fin])
        chunks.append(chunk)
        i     += chunk_size - overlap
    return chunks


def _parse_csv(contenido: str) -> list[str]:
    """Divide un CSV en chunks por grupos de filas con cabecera."""
    lineas = [l for l in contenido.splitlines() if l.strip()]
    if not lineas: return []
    cabecera = lineas[0]
    filas    = lineas[1:]
    FILAS_POR_CHUNK = 25
    chunks = []
    for i in range(0, len(filas), FILAS_POR_CHUNK):
        grupo  = filas[i:i + FILAS_POR_CHUNK]
        chunk  = cabecera + "\n" + "\n".join(grupo)
        chunks.append(chunk)
    return chunks


def _parse_json(contenido: str) -> list[str]:
    """Divide JSON en chunks."""
    import json as _json
    try:
        data = _json.loads(contenido)
        if isinstance(data, list):
            ITEMS_POR_CHUNK = 10
            chunks = []
            for i in range(0, len(data), ITEMS_POR_CHUNK):
                chunk = _json.dumps(data[i:i+ITEMS_POR_CHUNK], ensure_ascii=False, indent=1)
                chunks.append(chunk)
            return chunks
        return [contenido[:MAX_CHARS]]
    except Exception:
        return _split_texto(contenido)


def chunkar_documento(contenido: str, tipo: str = "txt") -> list[str]:
    """Divide un documento en chunks según su tipo."""
    if not contenido.strip(): return []
    t = tipo.lower().lstrip(".")
    if t in ("csv", "tsv"):   return _parse_csv(contenido)
    if t == "json":            return _parse_json(contenido)
    return _split_texto(contenido)


# ── TF-IDF simplificado ───────────────────────────────────────────────────────

def _tokenizar(texto: str) -> list[str]:
    """Tokeniza texto a palabras significativas."""
    texto = texto.lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    STOP  = {"de","la","el","en","y","a","que","los","las","del","al","por","con","un","una","es"}
    return [w for w in texto.split() if len(w) > 2 and w not in STOP]


def _tf(tokens: list[str]) -> dict:
    freq = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    n = max(len(tokens), 1)
    return {k: v/n for k, v in freq.items()}


def _idf(corpus_tokens: list[list[str]]) -> dict:
    n = len(corpus_tokens)
    df = {}
    for tokens in corpus_tokens:
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n+1)/(v+1))+1 for t, v in df.items()}


def _similitud_coseno(a: dict, b: dict) -> float:
    """Similitud coseno entre dos vectores TF-IDF."""
    dot  = sum(a.get(k,0)*b.get(k,0) for k in b)
    na   = math.sqrt(sum(v*v for v in a.values()))
    nb   = math.sqrt(sum(v*v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ── RAG principal ─────────────────────────────────────────────────────────────

class DocumentoRAG:
    """Índice RAG para un documento. Se construye una vez, se consulta muchas veces."""

    def __init__(self, contenido: str, nombre: str = "", tipo: str = "txt"):
        self.nombre = nombre
        self.tipo   = tipo
        self.chunks = chunkar_documento(contenido, tipo)
        if not self.chunks:
            self.chunks = [contenido[:MAX_CHARS]]

        # Vectorizar todos los chunks
        corpus_tokens = [_tokenizar(c) for c in self.chunks]
        idf           = _idf(corpus_tokens)
        self.vectores = [
            {t: freq * idf.get(t, 1) for t, freq in _tf(tokens).items()}
            for tokens in corpus_tokens
        ]
        logger.info("RAG '%s': %d chunks indexados", nombre, len(self.chunks))

    def buscar(self, query: str, top_k: int = TOP_K) -> str:
        """
        Encuentra los chunks más relevantes para la query y los devuelve
        como contexto listo para inyectar al prompt del agente.
        """
        q_tokens = _tokenizar(query)
        if not q_tokens:
            return self.chunks[0] if self.chunks else ""

        # Calcular IDF del corpus
        corpus_tokens = [_tokenizar(c) for c in self.chunks]
        idf   = _idf(corpus_tokens)
        q_vec = {t: freq * idf.get(t, 1) for t, freq in _tf(q_tokens).items()}

        # Puntuar chunks por similitud
        scores = [(i, _similitud_coseno(q_vec, v)) for i, v in enumerate(self.vectores)]
        scores.sort(key=lambda x: x[1], reverse=True)

        # Seleccionar top-k chunks únicos
        top = [self.chunks[i] for i, score in scores[:top_k] if score > 0]
        if not top:
            top = self.chunks[:min(top_k, len(self.chunks))]

        contexto = "\n\n---\n\n".join(top)
        return contexto[:MAX_CHARS]


# ── Cache de índices ──────────────────────────────────────────────────────────

_cache: dict[str, DocumentoRAG] = {}


def get_indice(archivo_id: str, contenido: str = "", nombre: str = "", tipo: str = "txt") -> DocumentoRAG:
    """Obtiene o crea el índice RAG para un archivo."""
    if archivo_id not in _cache:
        if not contenido:
            return None
        _cache[archivo_id] = DocumentoRAG(contenido, nombre, tipo)
    return _cache[archivo_id]


def limpiar_cache(archivo_id: str | None = None) -> None:
    """Limpia el cache RAG."""
    if archivo_id:
        _cache.pop(archivo_id, None)
    else:
        _cache.clear()


def buscar_en_archivo(archivo_id: str, query: str, contenido: str = "",
                      nombre: str = "", tipo: str = "txt") -> str:
    """API conveniente: indexa si no existe y busca."""
    indice = get_indice(archivo_id, contenido, nombre, tipo)
    if indice is None:
        return contenido[:MAX_CHARS] if contenido else ""
    return indice.buscar(query)
