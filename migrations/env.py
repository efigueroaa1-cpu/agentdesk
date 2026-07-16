import os
import sys
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Asegura que "core" sea importable sin importar desde donde se invoque
# alembic (CLI en el repo, o programaticamente desde core/database.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# NO se llama a fileConfig(config.config_file_name) aqui a proposito
# (hallazgo real, Fase 16/ADR-0014): AgentDesk corre `alembic upgrade
# head` como LIBRERIA en cada init_db() — no como CLI standalone.
# fileConfig() reconfigura el logger root con el [logger_root] level=WARNING
# de alembic.ini, lo que silenciaba en produccion TODO el logging de la
# app (incluidos los logs de auditoria forense) apenas corria una
# migracion. Alembic sigue logueando sus propios mensajes igual (usa el
# logger "alembic", que hereda la config que ya tenga el proceso host).

target_metadata = Base.metadata


def _url_efectiva() -> str:
    """
    Misma resolucion que core.database.init_db() (ADR-0005/0013):
    1. AGENTDESK_ALEMBIC_DB_URL — override explicito que init_db() setea
       cuando se llama con un db_path concreto (p.ej. tests con SQLite
       temporal), para que Alembic apunte al MISMO motor que el engine
       recien creado, no al de AGENTDESK_DB_URL/AppData por defecto.
    2. AGENTDESK_DB_URL — modo dual normal (planta/Postgres).
    3. SQLite en el data dir del usuario — zero-config de escritorio.
    Permite `alembic upgrade head` identico desde CLI y desde el arranque
    programatico de la app.
    """
    override = os.environ.get("AGENTDESK_ALEMBIC_DB_URL", "").strip()
    if override:
        return override
    db_url = os.environ.get("AGENTDESK_DB_URL", "").strip()
    if db_url:
        return db_url
    from core.path_manager import data_path
    db_path = data_path("") / "agentdesk.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


config.set_main_option("sqlalchemy.url", _url_efectiva())

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
