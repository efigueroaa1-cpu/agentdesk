# -*- coding: utf-8 -*-
"""
core/tools/factory.py — Registro central de herramientas (Factory Pattern).

Reemplaza el if/elif manual del dispatcher (que dejo pasar un NameError real
por un import olvidado, 2026-07-26) por un registro nombre -> adaptador. Cada
adaptador es `Callable[[dict, dict], str | Awaitable[str]]`:
  - arg 1: `argumentos` (los que envia el LLM).
  - arg 2: `contexto` ({"agente_id_clave", "user_id"} inyectado por el motor).

Agregar una herramienta nueva = una llamada a `registrar(...)` en __init__.py,
sin tocar el bucle de despacho. Maquina PURA: no importa nada de core.tools
(evita ciclos); __init__.py la puebla tras definir las implementaciones.
"""
from __future__ import annotations

from typing import Awaitable, Callable

Adaptador = Callable[[dict, dict], "str | Awaitable[str]"]

_REGISTRO: dict[str, Adaptador] = {}


def registrar(nombre: str, adaptador: Adaptador) -> None:
    """Registra (o reemplaza) el adaptador de una herramienta por nombre."""
    _REGISTRO[nombre] = adaptador


def resolver(nombre: str) -> Adaptador | None:
    """Devuelve el adaptador de `nombre`, o None si no esta registrada."""
    return _REGISTRO.get(nombre)


def herramientas_registradas() -> list[str]:
    """Nombres de todas las herramientas registradas (orden estable)."""
    return sorted(_REGISTRO)
