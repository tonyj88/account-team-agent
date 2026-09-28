"""Writes an ExtractionResult to the DB with resolved provenance spans.

Kept separate from extract/core.py (the LLM call) and extract/pipeline.py
(document selection/orchestration) so span resolution -- the part with real
logic worth testing -- can be unit-tested without a client or a DB session
full of unrelated fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from atb.extract.schema import ExtractionResult
from atb.models import ActionItem, ActionItemDirection, Contact, Decision, Document, Risk, _utcnow

# Bump when the extraction prompt/schema changes in a way that should make
# existing extractions stale (plan: "extraction version stamp ... makes
# re-extraction explicit and scopeable" -- this constant is what `atb
# extract --force` compares against, not a re-extract-everything default).
CURRENT_EXTRACTION_VERSION = 1


def _resolve_span(raw_text: str, quote: str) -> tuple[int | None, int | None]:
    """Locate `quote` verbatim in `raw_text`. Returns (None, None) if the
    model's quote doesn't appear exactly -- paraphrase, whitespace drift, or
    a hallucinated quote. The item is still stored (see schema.py docstring);
    only its span is missing."""
    if not quote:
        return None, None
    start = raw_text.find(quote)
    if start == -1:
        return None, None
    return start, start + len(quote)


@dataclass
class ExtractionWriteSummary:
    contacts: int = 0
    action_items: int = 0
    decisions: int = 0
    risks: int = 0
    unresolved_spans: int = 0


def apply_extraction(
    document: Document, result: ExtractionResult, session: Session
) -> ExtractionWriteSummary:
    """Writes every extracted item as a row scoped to `document.account_id`,
    and stamps the document as extracted. Caller must ensure
    `document.account_id` is set -- an extracted fact with no account is not
    useful and resolve() is where "no account" gets decided, not here."""
    assert document.account_id is not None, "apply_extraction requires a resolved document"
    account_id = document.account_id
    summary = ExtractionWriteSummary()

    for contact in result.contacts:
        char_start, char_end = _resolve_span(document.raw_text, contact.source_quote)
        if char_start is None:
            summary.unresolved_spans += 1
        session.add(
            Contact(
                account_id=account_id,
                name=contact.name,
                email=contact.email,
                title=contact.title,
                is_key_contact=contact.is_key_contact,
                source_document_id=document.id,
                char_start=char_start,
                char_end=char_end,
            )
        )
        summary.contacts += 1

    for item in result.action_items:
        char_start, char_end = _resolve_span(document.raw_text, item.source_quote)
        if char_start is None:
            summary.unresolved_spans += 1
        session.add(
            ActionItem(
                account_id=account_id,
                document_id=document.id,
                char_start=char_start,
                char_end=char_end,
                description=item.description,
                owner=item.owner,
                direction=ActionItemDirection(item.direction),
                due_date=_parse_due_date(item.due_date),
            )
        )
        summary.action_items += 1

    for decision in result.decisions:
        char_start, char_end = _resolve_span(document.raw_text, decision.source_quote)
        if char_start is None:
            summary.unresolved_spans += 1
        session.add(
            Decision(
                account_id=account_id,
                document_id=document.id,
                char_start=char_start,
                char_end=char_end,
                description=decision.description,
            )
        )
        summary.decisions += 1

    for risk in result.risks:
        char_start, char_end = _resolve_span(document.raw_text, risk.source_quote)
        if char_start is None:
            summary.unresolved_spans += 1
        session.add(
            Risk(
                account_id=account_id,
                document_id=document.id,
                char_start=char_start,
                char_end=char_end,
                description=risk.description,
            )
        )
        summary.risks += 1

    document.extraction_version = CURRENT_EXTRACTION_VERSION
    document.extracted_at = _utcnow()

    return summary


def _parse_due_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        # A due date the model stated in a format we didn't ask for is
        # better logged than lost, but strptime is not the citation
        # mechanism -- source_quote/char span still carries the real
        # evidence, so drop a malformed date rather than guess at it.
        return None
