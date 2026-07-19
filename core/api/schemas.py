"""
core/api/schemas.py — Modelos Pydantic de entrada para los routers de core/api/.

Extraído de core/api.py (Fase 17, ADR-0015) al modularizar el "archivo Dios"
en un paquete con un router por dominio (auth/agentes/sistema/monitor/
reportes). Centralizar los payloads aquí evita duplicarlos entre routers
y evita que un router dependa de otro solo para importar un modelo.
"""
from __future__ import annotations

from pydantic import BaseModel


class SchedulerUpdateRequest(BaseModel):
    activo:        bool | None = None
    intervalo_min: int  | None = None


class UpdateURLRequest(BaseModel):
    url: str


class EjecutarRequest(BaseModel):
    tarea:       str      = "reporte_ventas"
    datos_extra: str | None = None   # Texto directo para analizar
    archivo_id:  str | None = None   # ID de archivo subido con /upload


class ActualizarAgenteRequest(BaseModel):
    nombre:      str  | None = None
    tipo_ia:     str  | None = None
    area:        str  | None = None
    modelo:      str  | None = None
    temperatura: float| None = None
    idioma:      str  | None = None
    prompt_base: str  | None = None


class NuevoAgenteRequest(BaseModel):
    nombre:      str
    tipo_ia:     str
    area:        str
    modelo:      str      = "models/gemini-2.5-flash"
    temperatura: float    = 0.4
    idioma:      str      = "espanol"
    prompt_base: str      = ""


class ChatRequest(BaseModel):
    mensaje:    str
    agente_id:  str | None = None
    archivo_id: str | None = None
    sesion_id:  str        = "default"   # ID de sesión para memoria persistente


class GenerarPDFRequest(BaseModel):
    reporte:        dict
    titulo:         str  = "Informe de Análisis"
    subtitulo:      str  = ""
    nombre_agente:  str  = "AgentDesk"
    archivo_nombre: str  = ""
    empresa:        str  = "AgentDesk"


class AlertasConfigRequest(BaseModel):
    dolar_max: float | None = None
    dolar_min: float | None = None
    uf_max:    float | None = None
    ipc_max:   float | None = None


class PipelineConfigRequest(BaseModel):
    recursion_umbral: int   | None = None
    grounding_min:    int   | None = None
    logic_factor:     int   | None = None
    timeout_s:        float | None = None


class KillSwitchLicenciaRequest(BaseModel):
    contenido: str   # JSON completo de license.key (payload + firma RSA)


class CopilotoPlanRequest(BaseModel):
    objetivo:    str
    proyecto_id: str = ""


class CopilotoAplicarRequest(BaseModel):
    plan:        dict   # el plan retornado por /copiloto/planificar
    proyecto_id: str


class SkillExtraerRequest(BaseModel):
    nombre:      str
    descripcion: str = ""
    secuencia:   list[str] | None = None   # None → la más frecuente del minado


class KillSwitchToggleRequest(BaseModel):
    activo: bool


class ReloadRequest(BaseModel):
    agente_id: str | None = None   # None → recargar todos los agentes


class PresupuestoPayload(BaseModel):
    """Payload para POST /finanzas/analizar."""
    agente_id:   str
    presupuesto: dict
    periodos:    int = 6


class LlmResetRequest(BaseModel):
    """Payload para POST /diagnostico/llm/reset. Sin proveedor = todos."""
    proveedor: str | None = None


class MapReduceRequest(BaseModel):
    """Payload para POST /orquestador/mapreduce (Fase 21, ADR-0019)."""
    lider_id:         str
    trabajadores_ids: list[str]
    prompt:            str


class WhatsAppWebhookPayload(BaseModel):
    """Payload del webhook remoto (WhatsApp, curl, cron, etc.)."""
    mensaje:     str
    clave:       str            # contraseña en texto plano — validada contra MASTER_PASSWORD_HASH
    from_number: str = ""       # opcional: número origen para auditoría
