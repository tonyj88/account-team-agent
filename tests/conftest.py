"""Shared fixtures. Every test gets its own fresh SQLite file under
pytest's tmp_path -- never the developer's real data/atb.sqlite -- so
tests can freely create accounts and documents without polluting or
depending on real customer data."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from atb.store import db as db_module
from atb.store.db import init_db, session_scope


@pytest.fixture
def db_session(tmp_path: Path) -> Iterator[Session]:
    init_db(tmp_path / "test.sqlite")
    with session_scope() as session:
        yield session
    # Reset module globals so the next test's init_db() starts clean rather
    # than silently reusing this test's engine.
    db_module._engine = None
    db_module._SessionLocal = None
