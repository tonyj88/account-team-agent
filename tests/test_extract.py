"""Extraction: span resolution/writes, cost estimation, and run_extraction's
eligibility/dry-run/error-path behavior, all against a fake Anthropic client
-- mirrors plan Verification 2 at unit-test speed instead of a live call."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from atb.extract.core import ExtractionUsage, estimate_cost_usd, extract_document
from atb.extract.pipeline import run_extraction
from atb.extract.schema import (
    ExtractedActionItem,
    ExtractedContact,
    ExtractedDecision,
    ExtractedRisk,
    ExtractionResult,
)
from atb.extract.store import CURRENT_EXTRACTION_VERSION, apply_extraction
from atb.models import (
    Account,
    ActionItem,
    Contact,
    Decision,
    Document,
    DocumentSource,
    IngestLog,
    Risk,
)


def _make_document(session: Session, *, account_id: int | None, raw_text: str) -> Document:
    doc = Document(
        account_id=account_id,
        source=DocumentSource.FOLDER,
        origin_path="acme/note.md",
        raw_text=raw_text,
        content_hash=f"hash-{raw_text!r}",
    )
    session.add(doc)
    session.flush()
    return doc


# ---------------------------------------------------------------------------
# apply_extraction / span resolution
# ---------------------------------------------------------------------------


def test_apply_extraction_resolves_spans_and_writes_every_row_type(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()

    raw_text = "Jane Doe from Acme joined. We agreed to send the SOW by Friday. No blockers noted."
    doc = _make_document(db_session, account_id=account.id, raw_text=raw_text)

    result = ExtractionResult(
        contacts=[ExtractedContact(name="Jane Doe", source_quote="Jane Doe")],
        action_items=[
            ExtractedActionItem(
                description="Send the SOW",
                direction="we_owe",
                due_date="2026-09-25",
                source_quote="We agreed to send the SOW by Friday",
            )
        ],
        decisions=[
            ExtractedDecision(
                description="Agreed to send the SOW",
                source_quote="We agreed to send the SOW",
            )
        ],
        risks=[ExtractedRisk(description="none", source_quote="No blockers noted")],
    )

    summary = apply_extraction(doc, result, db_session)

    assert summary.contacts == 1
    assert summary.action_items == 1
    assert summary.decisions == 1
    assert summary.risks == 1
    assert summary.unresolved_spans == 0

    contact = db_session.execute(select(Contact)).scalar_one()
    assert contact.char_start == raw_text.find("Jane Doe")
    assert contact.char_end == contact.char_start + len("Jane Doe")

    action_item = db_session.execute(select(ActionItem)).scalar_one()
    assert action_item.direction.value == "we_owe"
    assert action_item.due_date is not None and action_item.due_date.year == 2026

    decision = db_session.execute(select(Decision)).scalar_one()
    assert decision.account_id == account.id

    risk = db_session.execute(select(Risk)).scalar_one()
    assert risk.account_id == account.id

    assert doc.extraction_version == CURRENT_EXTRACTION_VERSION
    assert doc.extracted_at is not None


def test_apply_extraction_stores_row_with_null_span_when_quote_not_found(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()

    doc = _make_document(db_session, account_id=account.id, raw_text="Some unrelated note text.")

    result = ExtractionResult(
        contacts=[ExtractedContact(name="Jane Doe", source_quote="text that never appears")]
    )
    summary = apply_extraction(doc, result, db_session)

    assert summary.contacts == 1
    assert summary.unresolved_spans == 1

    contact = db_session.execute(select(Contact)).scalar_one()
    assert contact.char_start is None
    assert contact.char_end is None


def test_apply_extraction_drops_malformed_due_date_but_keeps_the_item(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()

    raw_text = "We will follow up next week."
    doc = _make_document(db_session, account_id=account.id, raw_text=raw_text)

    result = ExtractionResult(
        action_items=[
            ExtractedActionItem(
                description="Follow up",
                direction="we_owe",
                due_date="next week",
                source_quote="We will follow up next week",
            )
        ]
    )
    apply_extraction(doc, result, db_session)

    action_item = db_session.execute(select(ActionItem)).scalar_one()
    assert action_item.due_date is None


# ---------------------------------------------------------------------------
# estimate_cost_usd
# ---------------------------------------------------------------------------


def test_estimate_cost_usd_prices_cached_tokens_at_a_discount():
    usage = ExtractionUsage(
        model="claude-sonnet-5", input_tokens=1000, output_tokens=100, cache_read_tokens=800
    )
    cost = estimate_cost_usd("claude-sonnet-5", usage)

    uncached = 200 * 2e-6
    cached = 800 * 2e-6 * 0.1
    output = 100 * 10e-6
    assert cost == uncached + cached + output


def test_estimate_cost_usd_falls_back_to_sonnet_pricing_for_unknown_model():
    usage = ExtractionUsage(model="some-future-model", input_tokens=1000, output_tokens=0)
    sonnet_usage = ExtractionUsage(model="claude-sonnet-5", input_tokens=1000, output_tokens=0)
    assert estimate_cost_usd("some-future-model", usage) == estimate_cost_usd(
        "claude-sonnet-5", sonnet_usage
    )


# ---------------------------------------------------------------------------
# run_extraction (fake anthropic client, no live API calls)
# ---------------------------------------------------------------------------


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 0


@dataclass
class _FakeToolUseBlock:
    input: dict
    type: str = "tool_use"


@dataclass
class _FakeTextBlock:
    text: str = "sorry, I can't do that"
    type: str = "text"


@dataclass
class _FakeResponse:
    content: list
    usage: _FakeUsage
    stop_reason: str = "tool_use"


class _FakeMessages:
    def __init__(
        self,
        result: ExtractionResult,
        *,
        error: Exception | None = None,
        omit_tool_use: bool = False,
        malformed_attempts: int = 0,
        malformed_payload: dict | None = None,
    ):
        self._result = result
        self._error = error
        self._omit_tool_use = omit_tool_use
        # First `malformed_attempts` calls return `malformed_payload` (a
        # tool_use block whose input fails ExtractionResult validation) --
        # lets a test script "bad shape, then clean" to exercise the retry
        # loop in extract_document without a live API call.
        self._malformed_attempts = malformed_attempts
        self._malformed_payload = malformed_payload if malformed_payload is not None else {}
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._omit_tool_use:
            return _FakeResponse(
                content=[_FakeTextBlock()], usage=_FakeUsage(), stop_reason="end_turn"
            )
        if self.calls <= self._malformed_attempts:
            block = _FakeToolUseBlock(input=self._malformed_payload)
            return _FakeResponse(content=[block], usage=_FakeUsage())
        block = _FakeToolUseBlock(input=self._result.model_dump(mode="json"))
        return _FakeResponse(content=[block], usage=_FakeUsage())


@dataclass
class _FakeClient:
    messages: _FakeMessages


def test_run_extraction_skips_unresolved_and_already_extracted_documents(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()

    unresolved = _make_document(db_session, account_id=None, raw_text="No account yet.")
    already_done = _make_document(db_session, account_id=account.id, raw_text="Old note.")
    already_done.extraction_version = CURRENT_EXTRACTION_VERSION
    eligible = _make_document(db_session, account_id=account.id, raw_text="Jane Doe attended.")
    db_session.flush()

    client = _FakeClient(messages=_FakeMessages(ExtractionResult()))
    summary = run_extraction(db_session, client, model="claude-sonnet-5")

    assert summary.extracted == 1
    assert client.messages.calls == 1
    assert unresolved.extraction_version is None
    assert eligible.extraction_version == CURRENT_EXTRACTION_VERSION


def test_run_extraction_force_reextracts_already_extracted_documents(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()

    doc = _make_document(db_session, account_id=account.id, raw_text="Jane Doe attended.")
    doc.extraction_version = CURRENT_EXTRACTION_VERSION
    db_session.flush()

    client = _FakeClient(messages=_FakeMessages(ExtractionResult()))
    summary = run_extraction(db_session, client, model="claude-sonnet-5", force=True)

    assert summary.extracted == 1
    assert client.messages.calls == 1


def test_run_extraction_dry_run_writes_no_rows_and_does_not_stamp_version(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()

    doc = _make_document(db_session, account_id=account.id, raw_text="Jane Doe attended.")
    db_session.flush()

    result = ExtractionResult(contacts=[ExtractedContact(name="Jane Doe", source_quote="Jane Doe")])
    client = _FakeClient(messages=_FakeMessages(result))
    summary = run_extraction(db_session, client, model="claude-sonnet-5", dry_run=True)

    assert summary.extracted == 0
    assert summary.skipped == 1
    assert summary.total_estimated_cost_usd > 0
    assert doc.extraction_version is None
    assert db_session.execute(select(Contact)).first() is None

    log = db_session.execute(select(IngestLog)).scalar_one()
    assert log.stage == "extract"
    assert log.status == "skipped_duplicate"


def test_run_extraction_respects_limit(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()
    for i in range(3):
        _make_document(db_session, account_id=account.id, raw_text=f"Note {i}")
    db_session.flush()

    client = _FakeClient(messages=_FakeMessages(ExtractionResult()))
    summary = run_extraction(db_session, client, model="claude-sonnet-5", limit=2)

    assert summary.extracted == 2
    assert client.messages.calls == 2


def test_run_extraction_logs_error_and_continues_instead_of_raising(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()
    _make_document(db_session, account_id=account.id, raw_text="Jane Doe attended.")
    db_session.flush()

    client = _FakeClient(messages=_FakeMessages(ExtractionResult(), error=RuntimeError("boom")))
    summary = run_extraction(db_session, client, model="claude-sonnet-5")

    assert summary.errors == 1
    assert summary.extracted == 0
    assert "boom" in summary.error_details[0]

    log = db_session.execute(select(IngestLog)).scalar_one()
    assert log.status == "error"
    assert log.detail == "boom"


def test_run_extraction_skips_empty_and_whitespace_only_documents_without_calling_api(
    db_session: Session,
):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()
    empty = _make_document(db_session, account_id=account.id, raw_text="")
    whitespace_only = _make_document(db_session, account_id=account.id, raw_text="   \n")
    db_session.flush()

    client = _FakeClient(messages=_FakeMessages(ExtractionResult()))
    summary = run_extraction(db_session, client, model="claude-sonnet-5")

    assert summary.extracted == 0
    assert summary.errors == 0
    assert summary.skipped_empty == 2
    assert client.messages.calls == 0

    logs = db_session.execute(select(IngestLog)).scalars().all()
    assert len(logs) == 2
    assert {log.document_id for log in logs} == {empty.id, whitespace_only.id}
    assert all(log.status == "skipped_empty" for log in logs)
    assert empty.extraction_version is None
    assert whitespace_only.extraction_version is None


# ---------------------------------------------------------------------------
# extract_document: missing tool_use block
# ---------------------------------------------------------------------------


def test_extract_document_raises_clear_error_when_no_tool_use_block(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()
    doc = _make_document(db_session, account_id=account.id, raw_text="Jane Doe attended.")
    db_session.flush()

    client = _FakeClient(
        messages=_FakeMessages(ExtractionResult(), omit_tool_use=True)
    )

    with pytest.raises(ValueError) as exc_info:
        extract_document(doc, model="claude-sonnet-5", client=client)

    message = str(exc_info.value)
    assert "end_turn" in message
    assert "text" in message
    # No tool_use block is retried like any other malformed response, not
    # raised on the first miss.
    assert client.messages.calls == 3


# ---------------------------------------------------------------------------
# extract_document: retry on non-deterministic malformed tool-use response
# ---------------------------------------------------------------------------


def test_extract_document_retries_malformed_response_then_succeeds(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()
    doc = _make_document(db_session, account_id=account.id, raw_text="Jane Doe attended.")
    db_session.flush()

    # Attempt 1 comes back wrapped under a spurious top-level "parameters"
    # key (one of the live-observed malformed shapes) -- fails validation.
    # Attempt 2 is clean.
    client = _FakeClient(
        messages=_FakeMessages(
            ExtractionResult(),
            malformed_attempts=1,
            malformed_payload={"contacts": [{"is_key_contact": True}]},
        )
    )

    result, usage = extract_document(doc, model="claude-sonnet-5", client=client)

    assert result == ExtractionResult()
    assert client.messages.calls == 2
    assert usage.attempts == 2
    # Every attempt is billed -- both calls' tokens must be summed, not just
    # the winning one's.
    assert usage.input_tokens == 200
    assert usage.output_tokens == 100


def test_extract_document_raises_last_error_after_exhausting_retries(db_session: Session):
    account = Account(name="Acme Corp")
    db_session.add(account)
    db_session.flush()
    doc = _make_document(db_session, account_id=account.id, raw_text="Jane Doe attended.")
    db_session.flush()

    client = _FakeClient(
        messages=_FakeMessages(
            ExtractionResult(),
            malformed_attempts=99,
            malformed_payload={"contacts": [{"is_key_contact": True}]},
        )
    )

    with pytest.raises(ValidationError):
        extract_document(doc, model="claude-sonnet-5", client=client)

    # Capped at _MAX_EXTRACTION_ATTEMPTS, not retried forever.
    assert client.messages.calls == 3


# ---------------------------------------------------------------------------
# ExtractionResult: coercion of malformed tool-use payload shapes
# ---------------------------------------------------------------------------


def test_extraction_result_coerces_items_wrapped_json_string():
    result = ExtractionResult.model_validate(
        {
            "action_items": (
                '{"items": ['
                '{"description": "Send SOW", "direction": "we_owe", '
                '"source_quote": "send the SOW"}, '
                '{"description": "Send follow-up", "direction": "they_owe", '
                '"source_quote": "send a follow-up"}'
                "]}"
            )
        }
    )
    assert len(result.action_items) == 2
    assert result.action_items[0].description == "Send SOW"


def test_extraction_result_coerces_bare_dict_json_string():
    result = ExtractionResult.model_validate(
        {
            "action_items": (
                '{"description": "Check in next week", "direction": "we_owe", '
                '"source_quote": "check in next week"}'
            )
        }
    )
    assert len(result.action_items) == 1
    assert result.action_items[0].description == "Check in next week"


def test_extraction_result_raises_on_non_json_garbage_string():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(
            {"action_items": '<parameter name="value">Send SOW</parameter>'}
        )


def test_extraction_result_native_list_payload_still_validates_unchanged():
    result = ExtractionResult.model_validate(
        {
            "action_items": [
                {
                    "description": "Send SOW",
                    "direction": "we_owe",
                    "source_quote": "send the SOW",
                }
            ]
        }
    )
    assert len(result.action_items) == 1
    assert result.action_items[0].description == "Send SOW"
