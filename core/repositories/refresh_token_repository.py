"""
core/repositories/refresh_token_repository.py — Persistencia de refresh
tokens rotativos (ADR-0008). Solo se manipulan hashes SHA-256; el valor del
token vive únicamente en el cliente.
"""
from __future__ import annotations

from datetime import datetime

from core.timeutil import utcnow


def guardar(username: str, token_hash: str, expira: datetime) -> None:
    from core.database import RefreshToken, get_session
    with get_session() as s:
        s.add(RefreshToken(token_hash=token_hash, username=username, expira=expira))
        s.commit()


def obtener(token_hash: str) -> dict | None:
    from core.database import RefreshToken, get_session
    with get_session() as s:
        r = s.query(RefreshToken).filter_by(token_hash=token_hash).first()
        if r is None:
            return None
        return {"username": r.username, "expira": r.expira, "revocado": bool(r.revocado)}


def revocar(token_hash: str) -> None:
    from core.database import RefreshToken, get_session
    with get_session() as s:
        r = s.query(RefreshToken).filter_by(token_hash=token_hash).first()
        if r:
            r.revocado = True
            s.commit()


def revocar_de_usuario(username: str) -> int:
    """Revoca TODA la familia de tokens del usuario (robo detectado / logout)."""
    from core.database import RefreshToken, get_session
    with get_session() as s:
        n = (s.query(RefreshToken)
             .filter_by(username=username, revocado=False)
             .update({"revocado": True}))
        s.commit()
        return n


def purgar_expirados() -> int:
    """Limpieza de tokens vencidos (higiene de la tabla)."""
    from core.database import RefreshToken, get_session
    with get_session() as s:
        n = s.query(RefreshToken).filter(RefreshToken.expira < utcnow()).delete()
        s.commit()
        return n
