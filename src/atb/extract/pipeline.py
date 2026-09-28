"""Selects eligible documents and runs extract/core.py + extract/store.py
over each one, logging cost/token spend to IngestLog the same way
ingest/pipeline.py logs ingest outcomes (plan: "ingest history and cost
history are the same table").

Eligible = resolved to an account (account_id is not null -- an unresolved
document has nowhere to attach extracted facts) and not yet extracted at
the current version, unless `force=True`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from atb.extract.core import ExtractionUsage, extract_document
from atb.extract.store import CURRENT_EXTRACTION_VERSION, apply_extraction
from atb.models import Document, IngestLog


@dataclass
class ExtractionSummary:
    extracted: int = 0
    skipped: int = 0
    skipped_empty: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)
    total_estimated_cost_usd: float = 0.0


def _eligible_documents(session: Session, *, limit: int | None, force: bool) -> list[Document]:
    stmt = select(Document).where(Document.account_id.is_not(None))
    if not force:
        stmt = stmt.where(
            (Document.extraction_version.is_(None))
            | (Document.extraction_version < CURRENT_EXTRACTION_VERSION)
        )
    stmt = stmt.order_by(Document.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().all())


def run_extraction(
    session: Session,
    client: anthropic.Anthropic,
    *,
    model: str,
    limit: int | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> ExtractionSummary:
    """Runs extraction over eligible documents. In `dry_run`, still calls the
    model (so the reported cost is real, not guessed) but writes nothing --
    neither the extracted rows nor the extraction_version stamp -- so a
    dry run can be repeated freely (plan: "--dry-run on the ingest CLI")."""
    summary = ExtractionSummary()
    documents = _eligible_documents(session, limit=limit, force=force)

    for document in documents:
        # Pre-flight: the API rejects an empty (or whitespace-only) user
        # message outright ("messages.0: user messages must have non-empty
        # content"), seen live on a genuinely empty note. That's not an
        # extraction failure, it's nothing to extract -- log it as a skip,
        # not an error, and deliberately don't stamp extraction_version so
        # a future non-force run retries automatically if the note ever
        # gets real content (at the cost of re-logging every run til then).
        if not document.raw_text or not document.raw_text.strip():
            summary.skipped_empty += 1
            session.add(
                IngestLog(
                    document_id=document.id,
                    origin_path=document.origin_path,
                    stage="extract",
                    status="skipped_empty",
                    detail="raw_text is empty or whitespace-only; nothing to extract",
                    model=model,
                )
            )
            continue

        # Broad on purpose: a network error, a rate limit, or a response
        # that fails schema validation must not abort the whole run --
        # every document still gets an IngestLog row (ingest/pipeline.py's
        # same guarantee, extended to this stage).
        try:
            result, usage = extract_document(document, model=model, client=client)
        except Exception as exc:
            summary.errors += 1
            summary.error_details.append(f"document {document.id}: {exc}")
            session.add(
                IngestLog(
                    document_id=document.id,
                    origin_path=document.origin_path,
                    stage="extract",
                    status="error",
                    detail=str(exc),
                    model=model,
                )
            )
            continue

        summary.total_estimated_cost_usd += usage.estimated_cost_usd

        if dry_run:
            summary.skipped += 1
            _log_usage(session, document, usage, status="skipped_duplicate", detail="dry_run")
            continue

        write_summary = apply_extraction(document, result, session)
        summary.extracted += 1
        _log_usage(
            session,
            document,
            usage,
            status="ok",
            detail=(
                f"contacts={write_summary.contacts} action_items={write_summary.action_items} "
                f"decisions={write_summary.decisions} risks={write_summary.risks} "
                f"unresolved_spans={write_summary.unresolved_spans} attempts={usage.attempts}"
            ),
        )

    return summary


def _log_usage(
    session: Session, document: Document, usage: ExtractionUsage, *, status: str, detail: str
) -> None:
    session.add(
        IngestLog(
            document_id=document.id,
            origin_path=document.origin_path,
            stage="extract",
            status=status,
            detail=detail,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            estimated_cost_usd=usage.estimated_cost_usd,
        )
    )
