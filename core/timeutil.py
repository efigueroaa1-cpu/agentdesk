"""
core/timeutil.py — Utilidades de tiempo.

Reemplazo central de datetime.utcnow(), deprecado desde Python 3.12.
Devuelve UTC *naive* (sin tzinfo), igual que utcnow(), porque toda la
persistencia (SQLite via SQLAlchemy) y las comparaciones del proyecto
usan datetimes naive — mezclar aware/naive lanza TypeError.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """UTC actual como datetime naive (drop-in de datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
