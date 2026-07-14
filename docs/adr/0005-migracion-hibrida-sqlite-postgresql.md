# ADR-0005 — Migración híbrida SQLite → PostgreSQL (Persistencia Industrial)

- **Estado:** Aceptado
- **Fecha:** 2026-07-14
- **Relacionado:** ADR-0004 (conectividad OT), ADR-0002 (capas)

## Contexto

SQLite es excelente para el escenario actual: app de escritorio mono-usuario,
cero administración, un archivo en `%APPDATA%\AgentDesk`. Pero la Fase 6/7
apunta a plantas con **10+ estaciones** emitiendo telemetría concurrente, y
ahí SQLite muestra sus límites estructurales:

- **Un solo escritor a la vez:** WAL mejora la lectura concurrente, pero las
  escrituras siguen serializadas — con alta telemetría aparecen
  `database is locked` y colas de escritura.
- **Sin acceso en red nativo:** cada estación tendría su propio archivo, sin
  vista única de planta ni integridad transaccional entre estaciones.
- **Durabilidad ante cortes:** un servidor PostgreSQL con WAL propio y
  réplicas protege el historial de ejecuciones y la auditoría de seguridad
  mejor que un archivo local en un panel industrial.

## Decisión

**Modo dual controlado por `AGENTDESK_DB_URL`, con SQLite como defecto.**

```
(sin variable)                          → SQLite local + WAL (histórico)
AGENTDESK_DB_URL=sqlite:///C:/ruta.db   → SQLite en ruta explícita (tests/QA)
AGENTDESK_DB_URL=postgresql+psycopg2://user:pass@servidor:5432/agentdesk
                                        → PostgreSQL de planta
```

1. `core/database.py` construye el engine desde la URL; para servidores usa
   `pool_pre_ping=True` (redes de planta inestables), `pool_size=10` y
   `max_overflow=20` (10+ estaciones concurrentes).
2. El resto del sistema NO cambia: repositorios y servicios hablan con
   `get_session()`; los modelos SQLAlchemy son portables entre ambos motores.
3. Las credenciales jamás se loggean (la URL se enmascara antes de loggear).
4. El driver (`psycopg2-binary`) es dependencia **opcional** de planta —
   ver requirements.txt; el escritorio no lo necesita.

## Consecuencias

- El instalador de escritorio sigue siendo autocontenido (SQLite embebido).
- Desplegar en planta = levantar PostgreSQL + definir una variable de
  entorno; sin cambios de código ni de build.
- Restricción conocida: los `to_dict()` y consultas usan tipos portables;
  cualquier SQL crudo futuro debe validarse en ambos motores (el gate corre
  sobre SQLite — un pipeline CI contra PostgreSQL real queda como siguiente
  paso cuando exista infraestructura de planta).
- El backup/restore actual (ZIP del archivo SQLite) aplica solo al modo
  escritorio; en modo PostgreSQL la copia de seguridad es responsabilidad
  del servidor (pg_dump/réplicas).
