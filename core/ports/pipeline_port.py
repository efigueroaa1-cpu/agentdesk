"""
core/ports/pipeline_port.py — Puerto de configuración del Pipeline (ADR-0003).

Gestión de los umbrales de guardrails del PipelineProcessor (core/pipeline.py)
y de los umbrales de alertas económicas. Implementado por
core/services/pipeline_service.py; la persistencia es JSON en el data dir.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PipelineServicePort(Protocol):
    """Configuración de guardrails y alertas, agnóstica del transporte."""

    def get_config(self) -> dict:
        """Umbrales vigentes de los guardrails (con defaults)."""
        ...

    def set_config(self, cambios: dict) -> dict:
        """Actualiza umbrales; aplican en la próxima ejecución de agentes."""
        ...

    def get_alertas_config(self) -> dict:
        """Umbrales vigentes de alertas económicas (con defaults)."""
        ...

    def set_alertas_config(self, cambios: dict) -> dict:
        """Actualiza umbrales de alertas económicas."""
        ...
