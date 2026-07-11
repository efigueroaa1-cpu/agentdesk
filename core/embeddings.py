"""
core/embeddings.py — Embeddings semánticos reales con TF-IDF + PCA.

En lugar de posiciones matemáticas ficticias, calcula posiciones 3D
basadas en el contenido real de los agentes:
  - prompt_base (instrucción del rol)
  - nombre + área
  - historial de tareas ejecutadas

Agentes similares (mismo dominio, misma área, prompts parecidos) → cercanos en 3D.
Agentes distintos → separados en 3D.

No requiere modelos de ML pesados — usa TF-IDF + PCA de scikit-learn (~30 MB).
"""
from __future__ import annotations
import logging
import math

logger = logging.getLogger(__name__)

AREA_COLORS = {
    "Finanzas":    "#00d4ff",
    "Mecánica":    "#00ff9d",
    "RRHH":        "#f59e0b",
    "Logística":   "#8b5cf6",
    "Marketing":   "#ef4444",
    "Legal":       "#f97316",
    "Tecnología":  "#06b6d4",
    "Operaciones": "#84cc16",
    "General":     "#64748b",
}


def _texto_agente(ag: dict, historial: list[dict] | None = None) -> str:
    """Construye un texto representativo de un agente para vectorizar."""
    partes = [
        ag.get("nombre", ""),
        ag.get("area", "General"),
        ag.get("prompt_base", ""),
        ag.get("idioma", "español"),
    ]
    # Añadir resúmenes de ejecuciones pasadas
    if historial:
        for ej in historial[:5]:
            if ej.get("resumen"):
                partes.append(ej["resumen"][:200])
    return " ".join(p for p in partes if p).lower()


def _tfidf_python(corpus: list[str]) -> list[list[float]]:
    """TF-IDF puro en Python (sin sklearn). Funciona en el bundle PyInstaller."""
    import math as _math

    # Tokenizar
    docs = [text.lower().split() for text in corpus]
    all_words = sorted(set(w for doc in docs for w in doc))
    if not all_words:
        return [[0.0] * 1] * len(docs)

    n = len(docs)
    # IDF
    idf = {}
    for w in all_words:
        df = sum(1 for doc in docs if w in doc)
        idf[w] = _math.log((n + 1) / (df + 1)) + 1

    # TF-IDF matrix
    matrix = []
    for doc in docs:
        freq = {}
        for w in doc:
            freq[w] = freq.get(w, 0) + 1
        total = max(len(doc), 1)
        row = [(freq.get(w, 0) / total) * idf[w] for w in all_words]
        # L2 normalizar
        norm = _math.sqrt(sum(v*v for v in row)) or 1
        matrix.append([v / norm for v in row])
    return matrix


def _pca_python(X: list[list[float]], k: int = 3) -> list[list[float]]:
    """PCA simplificado en Python puro — sin numpy."""
    import math as _math
    n  = len(X)
    if n < 2: return [[0.0, 0.0, 0.0] for _ in X]
    d  = len(X[0])
    k  = min(k, n - 1, d)

    # Centrar
    means = [sum(X[i][j] for i in range(n)) / n for j in range(d)]
    Xc    = [[X[i][j] - means[j] for j in range(d)] for i in range(n)]

    # Power iteration para obtener k vectores propios aproximados
    import random
    rng = random.Random(42)
    vecs = []
    for _ in range(k):
        v = [rng.gauss(0, 1) for _ in range(d)]
        # Deflactar vectores anteriores
        for prev in vecs:
            dot = sum(v[j]*prev[j] for j in range(d))
            v   = [v[j] - dot*prev[j] for j in range(d)]
        for _it in range(20):
            # Av
            Av = [sum(Xc[i][j]*v[j] for j in range(d)) for i in range(n)]
            v_new = [sum(Av[i]*Xc[i][j] for i in range(n)) for j in range(d)]
            # Normalizar
            norm = _math.sqrt(sum(x*x for x in v_new)) or 1
            v_new = [x/norm for x in v_new]
            # Deflactar
            for prev in vecs:
                dot = sum(v_new[j]*prev[j] for j in range(d))
                v_new = [v_new[j] - dot*prev[j] for j in range(d)]
            norm2 = _math.sqrt(sum(x*x for x in v_new)) or 1
            v = [x/norm2 for x in v_new]
        vecs.append(v)

    # Proyectar: coords = Xc @ V
    coords = []
    for i in range(n):
        row = [sum(Xc[i][j]*vecs[comp][j] for j in range(d)) for comp in range(k)]
        while len(row) < 3: row.append(0.0)
        coords.append(row)

    # Normalizar a [-5, 5]
    for dim in range(3):
        vals = [coords[i][dim] for i in range(n)]
        mn, mx = min(vals), max(vals)
        rng2 = mx - mn
        for i in range(n):
            coords[i][dim] = (coords[i][dim] - mn) / rng2 * 10 - 5 if rng2 > 0 else 0.0

    return coords


def calcular_embeddings(agentes: list[dict], historial_por_agente: dict | None = None) -> list[dict]:
    """
    Calcula coordenadas 3D semánticas para una lista de agentes.
    Usa TF-IDF + PCA puros en Python (sin sklearn) para compatibilidad con PyInstaller.
    """
    if not agentes:
        return []

    hist = historial_por_agente or {}

    try:
        corpus = [_texto_agente(ag, hist.get(ag.get("id", ""), [])) for ag in agentes]

        if len(agentes) < 2:
            return _posiciones_fallback(agentes)

        X      = _tfidf_python(corpus)
        coords = _pca_python(X, k=3)
        logger.info("Embeddings TF-IDF+PCA (pure Python): %d agentes", len(agentes))

    except Exception as exc:
        logger.warning("Embeddings falló (%s) — fallback circular", exc)
        return _posiciones_fallback(agentes)

    # ── Construir puntos ──────────────────────────────────────────────────────
    puntos: list[dict] = []
    import random

    for i, ag in enumerate(agentes):
        aid   = ag.get("id", f"ag_{i}")
        area  = ag.get("area", "General")
        color = AREA_COLORS.get(area, "#64748b")
        x, y, z = float(coords[i][0]), float(coords[i][1]), float(coords[i][2])

        # Nodo principal del agente
        puntos.append({
            "id":    aid,
            "nombre": ag.get("nombre", aid),
            "area":  area,
            "color": color,
            "x": x, "y": y, "z": z,
            "size": 0.9,
            "tipo": "agente",
            "modelo":     ag.get("modelo", ""),
            "temperatura":ag.get("temperatura", 0.4),
            "info": f"{ag.get('modelo','').replace('models/','')[:20]} · semantic",
        })

        # Satélites alrededor del punto del agente
        rng = random.Random(i * 7919 + 31337)
        n_sats = 10 + len(hist.get(aid, [])) * 2
        for j in range(min(n_sats, 20)):
            spread = 1.5
            puntos.append({
                "id":     f"{aid}_s{j}",
                "parentId": aid,
                "nombre": ag.get("nombre", aid),
                "area":   area,
                "color":  color,
                "x": x + (rng.random() - 0.5) * spread * 2,
                "y": y + (rng.random() - 0.5) * spread,
                "z": z + (rng.random() - 0.5) * spread * 2,
                "size":  (0.3 + rng.random() * 0.5) * 0.45,
                "tipo":  "satélite",
            })

    return puntos


def _posiciones_fallback(agentes: list[dict]) -> list[dict]:
    """Posiciones distribuidas en círculo cuando TF-IDF no es posible."""
    import random
    puntos = []
    n = max(len(agentes), 1)
    for i, ag in enumerate(agentes):
        aid   = ag.get("id", f"ag_{i}")
        area  = ag.get("area", "General")
        color = AREA_COLORS.get(area, "#64748b")
        angle = (i / n) * 2 * math.pi
        r = 4.0
        x, y, z = r * math.cos(angle), (i - n/2) * 1.5, r * math.sin(angle)
        puntos.append({
            "id":    aid, "nombre": ag.get("nombre", aid),
            "area":  area, "color": color,
            "x": x, "y": y, "z": z,
            "size": 0.9, "tipo": "agente",
        })
        rng = random.Random(i * 7919)
        for j in range(10):
            puntos.append({
                "id": f"{aid}_s{j}", "parentId": aid,
                "nombre": ag.get("nombre", aid), "area": area, "color": color,
                "x": x+(rng.random()-.5)*2, "y": y+(rng.random()-.5)*1.5, "z": z+(rng.random()-.5)*2,
                "size": 0.35, "tipo": "satélite",
            })
    return puntos
