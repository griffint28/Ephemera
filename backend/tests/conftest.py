import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ephemera import db
from ephemera.models import Base

FIXTURES = Path(__file__).parent / "fixtures"
REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"
# Illustrative workload values for hand-built Satellite rows.
WORKLOAD = {"storage_capacity_gb": 150.0, "generation_rate_gb_per_hour": 3.0, "downlink_rate_gb_per_min": 1.0}


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db.set_engine(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Session:  # type: ignore[no-untyped-def]
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


@pytest.fixture
def db_env(monkeypatch):  # type: ignore[no-untyped-def]
    """Settings need DB_* to exist even when tests swap in SQLite."""
    from ephemera.settings import get_settings

    for key, value in {"DB_NAME": "test", "DB_USER": "test", "DB_PASSWORD": "test"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CONFIG_DIR", str(REPO_CONFIG))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def load_omm(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)
