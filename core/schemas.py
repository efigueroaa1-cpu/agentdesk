from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, field_validator, model_validator


class ReporteAgente(BaseModel):
    resumen:   str
    kpis:      dict[str, str | int | float]
    tabla:     list[list[str]]
    evidencia: dict[str, str]   # KPI → fuente exacta en los datos de entrada

    @field_validator('resumen')
    @classmethod
    def resumen_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('resumen no puede ser una cadena vacía')
        return v

    @field_validator('tabla')
    @classmethod
    def tabla_requiere_encabezado(cls, v: list[list[str]]) -> list[list[str]]:
        if not v:
            raise ValueError('tabla debe contener al menos una fila de encabezados')
        if not all(isinstance(celda, str) for fila in v for celda in fila):
            raise ValueError('todas las celdas de tabla deben ser strings')
        return v

    @field_validator('kpis')
    @classmethod
    def kpis_no_vacio(cls, v: dict) -> dict:
        if not v:
            raise ValueError('kpis no puede ser un diccionario vacío')
        return v

    @field_validator('evidencia')
    @classmethod
    def evidencia_no_vacia(cls, v: dict) -> dict:
        if not v:
            raise ValueError(
                "evidencia no puede estar vacío — el agente debe citar "
                "la fuente de cada KPI a partir de los datos de entrada."
            )
        return v


class AgentConfig(BaseModel):
    """
    Valida los parámetros dinámicos de un agente antes de aplicarlos.
    Usado por AgentBase.reload_config() para garantizar rollback seguro.
    """
    nombre:      str
    tipo_ia:     str
    modelo:      str
    temperatura: float
    idioma:      str
    area:        str           # dominio funcional: "Finanzas", "Mecanica", etc.
    prompt_base: str = ""
    ubicacion:   dict | None = None  # {"lat": float, "lng": float, "label": str}

    # ── id es opcional: está en config.json pero no se usa en runtime ─────────
    id: str = ""

    @field_validator("nombre", "tipo_ia")
    @classmethod
    def campos_identidad_no_vacios(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("nombre y tipo_ia no pueden ser cadenas vacías")
        return v.strip()

    @field_validator("modelo")
    @classmethod
    def modelo_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("modelo no puede ser una cadena vacía")
        return v.strip()

    @field_validator("temperatura")
    @classmethod
    def temperatura_en_rango(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"temperatura debe estar entre 0.0 y 1.0, se recibió {v}"
            )
        return round(v, 4)

    @field_validator("idioma")
    @classmethod
    def idioma_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("idioma no puede ser una cadena vacía")
        return v.strip()

    @field_validator("area")
    @classmethod
    def area_no_vacia(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "area no puede ser vacía. Ejemplos: 'Finanzas', 'Mecanica', 'General'."
            )
        return v.strip().title()   # normaliza a "Finanzas" aunque llegue "finanzas"

    # ── Campos opcionales de encadenamiento y finanzas ────────────────────────
    siguiente_agente_id: str | None = None
    presupuesto: "PresupuestoConfig | None" = None


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMAS FINANCIEROS
# ═══════════════════════════════════════════════════════════════════════════════

class IndicadorChile(BaseModel):
    """Indicadores económicos en tiempo real del Banco Central de Chile."""
    uf:        float
    dolar:     float
    euro:      float
    ipc:       float
    timestamp: datetime

    @field_validator("uf", "dolar", "euro")
    @classmethod
    def valor_positivo(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Los valores de indicadores deben ser positivos")
        return round(v, 4)

    @field_validator("ipc")
    @classmethod
    def ipc_en_rango(cls, v: float) -> float:
        if not (-50.0 <= v <= 100.0):
            raise ValueError(f"IPC fuera de rango razonable: {v}")
        return round(v, 4)


class PresupuestoItem(BaseModel):
    """Partida individual de un presupuesto (ingreso o egreso)."""
    concepto: str
    monto:    float
    tipo:     Literal["ingreso", "egreso"]

    @field_validator("concepto")
    @classmethod
    def concepto_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("concepto de presupuesto no puede estar vacío")
        return v.strip()

    @field_validator("monto")
    @classmethod
    def monto_no_negativo(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"monto no puede ser negativo: {v}")
        return round(v, 2)


class PresupuestoConfig(BaseModel):
    """Presupuesto completo de un agente con validación estructural."""
    items:   list[PresupuestoItem]
    moneda:  str = "CLP"
    periodo: Literal["mensual", "trimestral", "anual"] = "mensual"

    @field_validator("items")
    @classmethod
    def items_no_vacios(cls, v: list) -> list:
        if not v:
            raise ValueError("presupuesto debe tener al menos un ítem")
        return v

    @field_validator("moneda")
    @classmethod
    def moneda_valida(cls, v: str) -> str:
        permitidas = {"CLP", "USD", "EUR", "UF"}
        v = v.upper().strip()
        if v not in permitidas:
            raise ValueError(f"moneda '{v}' no soportada. Use: {permitidas}")
        return v

    @property
    def total_ingresos(self) -> float:
        return round(sum(i.monto for i in self.items if i.tipo == "ingreso"), 2)

    @property
    def total_egresos(self) -> float:
        return round(sum(i.monto for i in self.items if i.tipo == "egreso"), 2)

    @property
    def flujo_neto(self) -> float:
        return round(self.total_ingresos - self.total_egresos, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMAS GANTT
# ═══════════════════════════════════════════════════════════════════════════════

class GanttTaskInput(BaseModel):
    """Datos validados para crear o actualizar una tarea en el Gantt."""
    proyecto_id:   str
    nombre:        str
    agente_id:     str = ""
    inicio_plan:   datetime
    duracion_dias: float
    dependencias:  list[int] = []   # IDs de tareas predecesoras (Fin a Inicio)
    color:         str = "#00d4ff"

    @field_validator("nombre", "proyecto_id")
    @classmethod
    def no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("nombre y proyecto_id no pueden estar vacíos")
        return v.strip()

    @field_validator("duracion_dias")
    @classmethod
    def duracion_positiva(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"duracion_dias debe ser positiva, recibido: {v}")
        return round(v, 2)

    @field_validator("color")
    @classmethod
    def color_hex(cls, v: str) -> str:
        import re
        if not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError(f"color debe ser hex (#RRGGBB), recibido: {v}")
        return v.lower()

    @field_validator("dependencias")
    @classmethod
    def dependencias_positivas(cls, v: list[int]) -> list[int]:
        if any(i <= 0 for i in v):
            raise ValueError("IDs de dependencias deben ser enteros positivos")
        return list(set(v))   # eliminar duplicados


class GanttProgresoUpdate(BaseModel):
    """Update de avance de una tarea (0–100 %)."""
    pct_completado: float
    inicio_real:    datetime | None = None
    fin_real:       datetime | None = None

    @field_validator("pct_completado")
    @classmethod
    def pct_en_rango(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError(f"pct_completado debe estar entre 0 y 100, recibido: {v}")
        return round(v, 1)


class FlujoCajaProyeccion(BaseModel):
    """Punto de proyección de flujo de caja en un mes futuro."""
    mes:             int
    ingreso_proy:    float
    egreso_proy:     float
    flujo_neto_proy: float
    acumulado:       float

    @model_validator(mode="after")
    def calcular_flujo(self) -> "FlujoCajaProyeccion":
        self.flujo_neto_proy = round(self.ingreso_proy - self.egreso_proy, 2)
        return self
