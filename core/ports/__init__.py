"""
core/ports — Interfaces (Protocol) de la Arquitectura Hexagonal.

Regla (ADR-0002): este paquete solo importa stdlib y core.domain. Define QUÉ
necesita el núcleo; los adaptadores (repositories/, api) definen CÓMO.
"""
from core.ports.auth_port import AuthPort, UserRepositoryPort            # noqa: F401
from core.ports.telemetry_port import MetricEvent, TelemetryPort         # noqa: F401
