"""
config_loader: carga y valida config.json.

Usa path_manager.config_path() (Soberanía de Datos, 2026-07-20): la copia
ESCRIBIBLE en %APPDATA%\\AgentDesk, nunca la plantilla empaquetada con el
exe. Se bootstrapea sola la primera vez; ediciones del usuario y backups
restaurados sobreviven a reinstalaciones del binario.
"""

import json
from pathlib import Path
from core.path_manager import config_path


def load_config(path: str | Path | None = None) -> dict:
    """
    Carga config.json y lo devuelve como diccionario.

    Parámetros
    ----------
    path : ruta explícita (str o Path). Si se omite, usa config_path()
           (la copia escribible en %APPDATA%, bootstrapeada si hace falta).

    Retorna
    -------
    dict con la estructura completa (clave 'agents')

    Lanza
    -----
    FileNotFoundError  si el archivo no existe
    ValueError         si el JSON está malformado o falta la clave 'agents'
    """
    ruta = Path(path) if path is not None else config_path()

    if not ruta.exists():
        raise FileNotFoundError(f"Archivo de configuracion no encontrado: {ruta}")

    with open(ruta, encoding="utf-8") as f:
        config = json.load(f)

    if "agents" not in config:
        raise ValueError(f"'{ruta}' no contiene la clave 'agents'.")

    return config
