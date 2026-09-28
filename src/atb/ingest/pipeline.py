"""Wires connectors -> normalize -> dedup -> resolve -> store into one run.

This is the thing Phase 1's verification step actually exercises: drop a
mixed batch into the folder, run this, and re-running it must add nothing
(plan: Verification 1). Every document gets an IngestLog row regardless of
outcome -- ok, skipped_duplicate, or error -- so an ingest run's history is
never silently incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from atb.ingest.base import RawDocument, SourceConnector
from atb.models import Document, IngestLog, ReviewQueueItem
from atb.normalize.core import UnsupportedFormatError, normalize
from atb.normalize.dedup import content_hash
from atb.redact import Finding, redact_text
from atb.resolve.core import resolve


@dataclass
class IngestSummary:
    ingested: int = 0
    duplicates: int = 0
    unresolved: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)


def run_ingest(
    connectors: list[SourceConnector], session: Session, *, redaction_enabled: bool = True
) -> IngestSummary:
    """Runs every enabled connector's poll() through the pipeline. Connectors
    that are disabled yield nothing (see each connector's poll()), so passing
    every configured connector here regardless of its `enabled` flag is safe
    and is how callers should use this.

    `redaction_enabled` is threaded through from Settings.redaction.enabled
    rather than imported here directly, so this function stays testable
    without a Settings object -- same reasoning as chunk_size/chunk_overlap
    being parameters of run_indexing rather than pulled from config inside
    it."""
    summary = IngestSummary()
    for connector in connectors:
        for raw in connector.poll():
            _ingest_one(raw, session, summary, redaction_enabled=redaction_enabled)
    return summary


def _ingest_one(
    raw: RawDocument, session: Session, summary: IngestSummary, *, redaction_enabled: bool = True
) -> None:
    try:
        normalized = normalize(raw)
    except UnsupportedFormatError as exc:
        summary.errors += 1
        summary.error_details.append(str(exc))
        session.add(
            IngestLog(
                document_id=None,
                origin_path=raw.origin_path,
                stage="ingest",
                status="error",
                detail=str(exc),
            )
        )
        return

    # Redact BEFORE anything downstream sees the text -- content_hash,
    # raw_text storage, resolve() hints all operate on the cleaned text from
    # this point on. See redact.py's module docstring for why this has to
    # happen here rather than closer to the LLM or the vector store.
    redaction_findings: list[Finding] = []
    if redaction_enabled:
        redaction = redact_text(normalized.text)
        normalized.text = redaction.text
        redaction_findings = redaction.findings

    hash_ = content_hash(normalized.text)
    existing = session.execute(select(Document.id).where(Document.content_hash == hash_)).first()
    if existing is not None:
        summary.duplicates += 1
        session.add(
            IngestLog(
                document_id=existing[0],
                origin_path=raw.origin_path,
                stage="ingest",
                status="skipped_duplicate",
            )
        )
        return

    document = Document(
        source=raw.source,
        origin_path=raw.origin_path,
        author=normalized.author,
        title=normalized.title,
        raw_text=normalized.text,
        content_hash=hash_,
        occurred_at=raw.occurred_at,
    )
    session.add(document)
    session.flush()  # assign document.id before resolve()/review queue reference it

    resolution = resolve(normalized, session)
    if resolution.account_id is not None:
        document.account_id = resolution.account_id
    else:
        summary.unresolved += 1
        session.add(
            ReviewQueueItem(
                document_id=document.id,
                candidate_names=resolution.candidates,
                reason=resolution.reason or "unresolved",
                attempted_hint=resolution.attempted_text,
            )
        )

    summary.ingested += 1
    resolution_detail = (
        f"matched_via={resolution.matched_via}" if resolution.matched_via else "unresolved"
    )
    detail = resolution_detail
    if redaction_findings:
        # Rule names + counts only -- never a value, never a line number
        # here (findings already carry that; this is just the summary line
        # a human skims in IngestLog without opening the finding detail).
        rule_counts: dict[str, int] = {}
        for finding in redaction_findings:
            rule_counts[finding.rule] = rule_counts.get(finding.rule, 0) + 1
        counts_str = ", ".join(f"{rule}={n}" for rule, n in sorted(rule_counts.items()))
        detail = f"{resolution_detail} redacted={len(redaction_findings)} ({counts_str})"
    session.add(
        IngestLog(
            document_id=document.id,
            origin_path=raw.origin_path,
            stage="ingest",
            status="ok",
            detail=detail,
        )
    )
