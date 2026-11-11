"""Engine and sessions. The engine is created lazily from settings on first use."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ephemera.settings import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        set_engine(create_engine(get_settings().database_url, pool_pre_ping=True))
    assert _engine is not None
    return _engine


def set_engine(engine: Engine) -> None:
    """Install an engine (tests use this to point everything at SQLite)."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session that commits on success and rolls back on error."""
    get_engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
