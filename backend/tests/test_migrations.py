from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from ephemera.models import Base

BACKEND = Path(__file__).resolve().parents[1]


def _config(connection) -> Config:  # type: ignore[no-untyped-def]
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["connection"] = connection
    cfg.attributes["configure_logging"] = False
    return cfg


def test_migrations_match_models(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        command.upgrade(_config(conn), "head")
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], f"migrations and models differ: {diff}"


def test_downgrade_to_base_and_back(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        command.upgrade(_config(conn), "head")
        command.downgrade(_config(conn), "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    with engine.begin() as conn:
        command.upgrade(_config(conn), "head")
    assert {"satellites", "stations", "orbital_elements", "passes"} <= set(inspect(engine).get_table_names())
