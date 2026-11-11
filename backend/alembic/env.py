"""Alembic environment.

Migrations are hand-written. A test upgrades an empty database and compares it against the
models, so the two cannot drift apart unnoticed. `alembic check` does the same against MariaDB.

Tests pass a live connection in `config.attributes["connection"]`; otherwise the connection
comes from the DB_* environment variables.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from ephemera.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        return
    from ephemera.settings import get_settings

    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        _configure(conn)


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not supported; run against a database.")
run_migrations_online()
