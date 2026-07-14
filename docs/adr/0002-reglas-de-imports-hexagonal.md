# ADR-0002 — Reglas de imports de la Arquitectura Hexagonal

- **Estado:** Aceptado
- **Fecha:** 2026-07-13
- **Guardián automático:** `scripts/gate.py` (invocado por `gate.ps1`)

## Contexto

`core/` creció como módulos planos donde la lógica de negocio, el SQL y los
endpoints HTTP se mezclan (ejemplo: el antiguo `core/auth.py` contenía bcrypt,
reglas RBAC, consultas SQLAlchemy y una dependencia FastAPI en el mismo archivo).
Para la fase industrial se necesita poder cambiar adaptadores (SQLite→otro motor,
REST→Modbus/OPC-UA) sin tocar el núcleo, y que un script pueda verificar la
arquitectura en cada gate.

## Decisión

Se establecen cuatro capas dentro de `core/` con reglas de dependencia estrictas
(las flechas indican "puede importar de"):

```
api.py / api_auth.py  ─→  services/  ─→  ports/  ─→  domain/
(adaptadores entrada)      │                            ▲
                           └─→  repositories/  ─────────┘
                                (adaptadores persistencia)
```

| Capa | Contenido | Puede importar | PROHIBIDO importar |
|------|-----------|----------------|--------------------|
| `core/domain/` | Entidades puras (`User`, `Agent`, `Task`) y reglas de negocio (`tiene_permiso`, jerarquía RBAC) | solo stdlib | FastAPI, SQLAlchemy, cualquier otro módulo de `core/` |
| `core/ports/` | Interfaces `Protocol` (`TelemetryPort`, `AuthPort`, `UserRepositoryPort`) | stdlib, `core.domain` | frameworks, `core.services`, `core.repositories`, capa api |
| `core/services/` | Lógica de negocio (`AuthService`) | `core.domain`, `core.ports`, repositorios vía inyección | **nada de la capa api** (`core.api`, `core.api_auth`), FastAPI/Starlette |
| `core/repositories/` | Adaptadores de persistencia SQLAlchemy | `core.domain`, `core.ports`, `core.database` | capa api, FastAPI/Starlette |

- **`domain/` es el núcleo puro:** si un archivo de `domain/` necesita un
  framework, la entidad está mal ubicada.
- **`ports/` son las interfaces:** definen QUÉ necesita el núcleo; nunca CÓMO.
- **`services/` nunca importan de la capa `api/`:** la dirección de dependencia
  es siempre adaptador→servicio, jamás al revés. La API es un detalle de entrega.
- Los módulos legados de `core/` (api.py, scheduler.py, …) migran incrementalmente;
  mientras tanto `core/auth.py` queda como fachada de compatibilidad que re-exporta
  el servicio (código nuevo importa `core.services.auth_service`).

## Cumplimiento

`scripts/gate.py` bloquea el gate si detecta: (1) imports que violen la tabla
anterior, (2) etiquetas TODO/FIXME/PATCH, (3) archivos nuevos de más de 500
líneas (los legados registrados solo pueden decrecer — regla de trinquete).

## Consecuencias

- La migración Auth/RBAC (primer caso aplicado) dejó: `domain/user.py`,
  `ports/auth_port.py`, `services/auth_service.py`, `repositories/user_repository.py`
  y el adaptador de entrada `api_auth.py`; api.py adelgazó >200 líneas.
- Los servicios se testean con repositorios falsos (inyección por constructor),
  sin levantar FastAPI ni SQLite.
- Un nodo industrial (Modbus/OPC-UA) entra como adaptador que implementa
  `TelemetryPort` sin modificar núcleo ni UI (ver ADR-0001).
