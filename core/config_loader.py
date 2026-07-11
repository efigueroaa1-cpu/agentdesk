"""
config_loader: carga y valida config.json.

Usa path_manager.resource_path() para que config.json se encuentre
tanto en desarrollo (ruta relativa) como en el ejecutable PyInstaller
(sys._MEIPASS), sin cambiar ninguna llamada en el resto del proyecto.
"""

import json
from pathlib import Path
from core.path_manager import resource_path


def load_config(path: str | Path | None = None) -> dict:
    """
    Carga config.json y lo devuelve como diccionario.

    Parámetros
    ----------
    path : ruta explícita (str o Path). Si se omite, usa resource_path("config.json"),
           que resuelve correctamente tanto en desarrollo como en el ejecutable.

    Retorna
    -------
    dict con la estructura completa (clave 'agents')

    Lanza
    -----
    FileNotFoundError  si el archivo no existe
    ValueError         si el JSON está malformado o falta la clave 'agents'
    """
    ruta = Path(path) if path is not None else resource_path("config.json")

    if not ruta.exists():
        raise FileNotFoundError(f"Archivo de configuracion no encontrado: {ruta}")

    with open(ruta, encoding="utf-8") as f:
        config = json.load(f)

    if "agents" not in config:
        raise ValueError(f"'{ruta}' no contiene la clave 'agents'.")

    return config
