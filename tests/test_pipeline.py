"""run_ingest end-to-end: connector -> normalize -> dedup -> resolve ->
store. Mirrors plan Verification 1 at unit-test speed instead of via the
CLI against real files."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from atb.ingest.base import RawDocument
from atb.ingest.pipeline import run_ingest
from atb.models import Account, Document, ReviewQueueItem
from atb.models import DocumentSource as Src


@dataclass
class _FakeConnector:
    docs: list[RawDocument]
    enabled: bool = True

    def poll(self):
        return list(self.docs) if self.enabled else []


def test_ingest_resolves_known_account_and_writes_document(db_session: Session):
    acme = Account(name="Acme Corp")
    db_session.add(acme)
    db_session.flush()

    connector = _FakeConnector(
        docs=[
            RawDocument(
                source=Src.FOLDER,
                origin_path="acme/note.md",
                filename="note.md",
                raw_text="---\ncustomer: Acme Corp\n---\nRenewal discussion.",
            )
        ]
    )
    summary = run_ingest([connector], db_session)
    assert summary.ingested == 1
    assert summary.unresolved == 0

    doc = db_session.execute(select(Document)).scalar_one()
    assert doc.account_id == acme.id


def test_ingest_unresolved_document_goes_to_review_queue(db_session: Session):
    connector = _FakeConnector(
        docs=[
            RawDocument(
                source=Src.FOLDER,
                origin_path="note.txt",
                filename="note.txt",
                raw_text="Some note with no customer signal at all.",
            )
        ]
    )
    summary = run_ingest([connector], db_session)
    assert summary.ingested == 1
    assert summary.unresolved == 1

    queue_items = db_session.execute(select(ReviewQueueItem)).scalars().all()
    assert len(queue_items) == 1
    doc = db_session.execute(select(Document)).scalar_one()
    assert doc.account_id is None
    assert queue_items[0].document_id == doc.id


def test_rerunning_ingest_against_same_content_adds_nothing(db_session: Session):
    connector = _FakeConnector(
        docs=[
            RawDocument(
                source=Src.FOLDER,
                origin_path="note.txt",
                filename="note.txt",
                raw_text="Same note.",
            )
        ]
    )
    first = run_ingest([connector], db_session)
    second = run_ingest([connector], db_session)

    assert first.ingested == 1
    assert second.ingested == 0
    assert second.duplicates == 1

    documents = db_session.execute(select(Document)).scalars().all()
    assert len(documents) == 1


def test_disabled_connector_yields_nothing(db_session: Session):
    connector = _FakeConnector(
        docs=[RawDocument(source=Src.FOLDER, origin_path="x.txt", filename="x.txt", raw_text="x")],
        enabled=False,
    )
    summary = run_ingest([connector], db_session)
    assert summary.ingested == 0


def test_unsupported_format_is_logged_as_error_not_a_crash(db_session: Session):
    connector = _FakeConnector(
        docs=[RawDocument(source=Src.FOLDER, origin_path="x.xyz", filename="x.xyz", raw_text="x")]
    )
    summary = run_ingest([connector], db_session)
    assert summary.errors == 1
    assert summary.ingested == 0


def test_ingested_document_is_already_redacted_in_the_db(db_session: Session):
    """redact.py's whole design premise -- raw_text must be clean before it
    is ever written, because citation spans/chunks are computed against it
    afterward. Uses a synthetic secret value only, never a real one."""
    from atb.models import IngestLog

    synthetic_token = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz01"
    acme = Account(name="Acme Corp")
    db_session.add(acme)
    db_session.flush()

    connector = _FakeConnector(
        docs=[
            RawDocument(
                source=Src.FOLDER,
                origin_path="acme/trial.md",
                filename="trial.md",
                raw_text=(
                    "---\ncustomer: Acme Corp\n---\n"
                    f"Trial server token:\n{synthetic_token}\nEnd of note."
                ),
            )
        ]
    )
    run_ingest([connector], db_session)

    doc = db_session.execute(select(Document)).scalar_one()
    assert synthetic_token not in doc.raw_text
    assert "[REDACTED:TOKEN]" in doc.raw_text

    log_entries = db_session.execute(select(IngestLog)).scalars().all()
    assert any("redacted=1" in (entry.detail or "") for entry in log_entries)
