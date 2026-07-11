import json
from core.path_manager import resource_path


class DataProvider:
    """
    Patrón de Fábrica para la gestión de fuentes de datos.
    Permite escalar hacia SQL, Cloud o APIs sin modificar el Orquestador.
    """

    @staticmethod
    def get_data(source_type, query):
        if source_type == "json":
            return DataProvider._read_json(resource_path("datos_trabajo.json"))
        elif source_type == "sql":
            return "Simulacion: Datos desde SQL"
        else:
            return f"Error: Fuente {source_type} no soportada."

    @staticmethod
    def _read_json(filepath):
        try:
            if not filepath.exists():
                return "Error: Archivo de datos no encontrado."
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return f"Error critico leyendo archivo: {e}"


def consultar_datos_seguros(query):
    return DataProvider.get_data("json", query)
