"""Session management and schema init.

No migration framework yet (Alembic is the obvious upgrade once the schema
stabilizes past the prototype) -- for now, init_db() is create-all, which is
enough for a single-file SQLite pilot that nobody else is writing to
concurrently. Revisit before the Postgres move mentioned in the plan
(Storage: SQLAlchemy over SQLite now, Postgres later).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from atb.models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(db_path: Path) -> Engine:
    """Create the engine, ensure the parent directory exists, and create any
    missing tables. Idempotent -- safe to call on every process start."""
    global _engine, _SessionLocal

    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    # SQLite defaults to DELETE journal mode and off-by-default foreign keys;
    # both matter once more than one connector writes concurrently.
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)

    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("init_db() has not been called yet")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session: commits on clean exit, rolls back
    and re-raises on error. Use as `with session_scope() as session: ...`."""
    if _SessionLocal is None:
        raise RuntimeError("init_db() has not been called yet")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
