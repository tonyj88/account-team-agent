"""End-to-end CLI tests: `atb accounts add`, `atb ingest`, `atb review
list/resolve` exactly as an operator would run them, including the
"resolving from the queue writes a new alias so it is never asked again"
promise from the plan."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from atb.cli import app
from atb.store import db as db_module

runner = CliRunner()


def _strip_ansi_codes(text: str) -> str:
    """Remove ANSI color escape codes from text for robust output assertions."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.fixture(autouse=True)
def _reset_db_module():
    yield
    db_module._engine = None
    db_module._SessionLocal = None


def _write_config(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        'db_path = "atb.sqlite"\n[intake.folder]\nenabled = true\npath = "drop"\n'
    )
    (tmp_path / "drop").mkdir()


def test_ingest_then_review_list_shows_unresolved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    (tmp_path / "drop" / "mystery.txt").write_text("A note about nothing in particular.")

    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi_codes(result.output)
    assert "ingested 1" in output
    assert "unresolved -> review queue 1" in output

    listing = runner.invoke(app, ["review", "list"])
    assert listing.exit_code == 0
    assert "mystery" in _strip_ansi_codes(listing.output)


def test_review_resolve_writes_alias_and_clears_queue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    (tmp_path / "drop" / "note.md").write_text(
        "---\ncustomer: mystery vendor call\n---\nFollow-up call."
    )

    create = runner.invoke(app, ["accounts", "add", "Acme Corp"])
    assert create.exit_code == 0

    first_ingest = runner.invoke(app, ["ingest"])
    assert "unresolved -> review queue 1" in _strip_ansi_codes(first_ingest.output)

    resolved = runner.invoke(app, ["review", "resolve", "1", "Acme Corp"])
    assert resolved.exit_code == 0, resolved.output
    assert "resolved" in _strip_ansi_codes(resolved.output)

    empty_queue = runner.invoke(app, ["review", "list"])
    assert "review queue is empty" in _strip_ansi_codes(empty_queue.output)

    # A second, unrelated note reusing the exact same ambiguous wording
    # should now resolve automatically -- the alias learned above must
    # actually be consulted by resolve(), not just recorded.
    (tmp_path / "drop" / "note2.md").write_text(
        "---\ncustomer: mystery vendor call\n---\nAnother call, same vendor."
    )
    second_ingest = runner.invoke(app, ["ingest"])
    output = _strip_ansi_codes(second_ingest.output)
    assert "unresolved -> review queue 0" in output
    assert "ingested 1" in output


def test_review_resolve_requires_create_flag_for_new_account(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    (tmp_path / "drop" / "note.txt").write_text("Unplaceable note.")

    runner.invoke(app, ["ingest"])
    result = runner.invoke(app, ["review", "resolve", "1", "Brand New Co"])
    assert result.exit_code != 0
    assert "--create" in _strip_ansi_codes(result.output)
