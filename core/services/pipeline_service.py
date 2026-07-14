"""
core/services/pipeline_service.py — Configuración del Pipeline y Alertas
(ADR-0003). Umbrales de los guardrails del PipelineProcessor (core/pipeline.py)
y de alertas económicas, persistidos como JSON en el data dir. Sin FastAPI.
"""
from __future__ import annotations

import json as _json
import logging

logger = logging.getLogger(__name__)

DEFAULTS_PIPELINE = {
    "recursion_umbral": 3,
    "grounding_min":    1000,
    "logic_factor":     100,
    "timeout_s":        5,
}

DEFAULTS_ALERTAS = {
    "umbrales": {
        "dolar_max": 1000,
        "dolar_min": 800,
        "uf_max":    45000,
        "ipc_max":   1.0,
    }
}


def _leer_json(nombre: str) -> dict | None:
    from core.path_manager import data_path
    cfg_path = data_path(nombre)
    if cfg_path.exists():
        try:
            return _json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _escribir_json(nombre: str, data: dict) -> None:
    from core.path_manager import data_path
    data_path("").mkdir(parents=True, exist_ok=True)
    data_path(nombre).write_text(_json.dumps(data, indent=2), encoding="utf-8")


class PipelineService:
    """Implementación de core.ports.pipeline_port.PipelineServicePort."""

    def get_config(self) -> dict:
        """Umbrales vigentes de los guardrails (defaults + overrides)."""
        stored = _leer_json("pipeline_config.json")
        if stored is not None:
            return {"config": {**DEFAULTS_PIPELINE, **stored}}
        return {"config": DEFAULTS_PIPELINE}

    def set_config(self, cambios: dict) -> dict:
        """Actualiza umbrales; aplican en la próxima ejecución de agentes."""
        current = _leer_json("pipeline_config.json") or {}
        updates = {k: v for k, v in cambios.items() if v is not None}
        current.update(updates)
        _escribir_json("pipeline_config.json", current)
        logger.info("Pipeline config actualizada", extra={"config": current})
        return {"ok": True, "config": current}

    def get_alertas_config(self) -> dict:
        """Umbrales vigentes de alertas económicas (defaults + overrides)."""
        stored = _leer_json("alertas_config.json")
        if stored is not None:
            return {"config": {**DEFAULTS_ALERTAS, **stored}}
        return {"config": DEFAULTS_ALERTAS}

    def set_alertas_config(self, cambios: dict) -> dict:
        """Actualiza umbrales de alertas económicas."""
        current = _leer_json("alertas_config.json") or {"umbrales": {}}
        updates = {k: v for k, v in cambios.items() if v is not None}
        current.setdefault("umbrales", {}).update(updates)
        _escribir_json("alertas_config.json", current)
        logger.info("Alertas config actualizada: %s", updates)
        return {"ok": True, "config": current}


# Instancia por defecto (estado en disco, no en memoria)
pipeline_service = PipelineService()
