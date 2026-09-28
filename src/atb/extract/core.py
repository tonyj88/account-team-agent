"""LLM structured extraction: one Document's raw_text -> ExtractionResult.

The system prompt (SYSTEM_PROMPT below) is byte-identical across every call
in a run, so it's sent with `cache_control` -- cheap to add, and the plan's
cost model assumes it (see plan: "Prompt caching on the extraction prefix").
Verify it actually engaged via `usage.cache_read_input_tokens` on the second
and later calls of a batch, not the first (plan: "Controls to build in").
"""

from __future__ import annotations

from dataclasses import dataclass

import anthropic
from pydantic import ValidationError

from atb.extract.schema import ExtractionResult
from atb.models import Document

SYSTEM_PROMPT = """\
You extract structured facts from one account team meeting note or call \
transcript. The account team (AE, CSM, Sales Engineer, TAMs) is "we"/"us"; \
the customer is "they"/"them".

Extract, strictly from what the text states -- never infer or guess:
- contacts: every person named as an attendee or otherwise identified, with \
email/title only if the text states them.
- action_items: commitments with a clear owner or clear direction. Set \
direction to "we_owe" if our team committed to do it, "they_owe" if the \
customer did. If the direction is genuinely ambiguous from the text, skip \
the item rather than guessing -- a wrong direction is worse than a missing \
item.
- decisions: things that were decided/agreed, not just discussed.
- risks: stated concerns, blockers, or churn signals -- not routine business.

For every item, copy `source_quote` verbatim from the document text (same \
whitespace and casing) -- do not paraphrase or summarize it. This is the \
only mechanism used to locate the item's source span, so an inexact quote \
means that item loses its citation.

If a category has nothing to report, return an empty list for it. An empty \
list is the correct answer for a document that simply doesn't mention that \
category -- do not force an example into it.

Never copy a credential, password, token, or API key into any output field \
-- not even inside a source_quote -- even if one appears in the source text. \
Redaction of the source itself happens upstream of this call; this is a \
defense-in-depth instruction, not the primary control.\
"""

# Verified against the claude-api skill (plan: "Cost model and controls"),
# cached 2026-06-24. $ per token, not per million -- pre-divided so
# estimate_cost_usd stays a plain multiply. Keep in sync with the plan's
# pricing table if these change; don't let a stale number silently drift.
_PRICE_PER_TOKEN_USD: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5e-6, 25e-6),
    "claude-sonnet-5": (2e-6, 10e-6),
    "claude-haiku-4-5": (1e-6, 5e-6),
}
_CACHE_READ_MULTIPLIER = 0.1


@dataclass
class ExtractionUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    attempts: int = 1

    @property
    def estimated_cost_usd(self) -> float:
        return estimate_cost_usd(self.model, self)


def estimate_cost_usd(model: str, usage: ExtractionUsage) -> float:
    """$ estimate for one call. Uncached input tokens at full price, cached
    input tokens at `_CACHE_READ_MULTIPLIER` (plan: cache reads price at
    0.1x). Falls back to Sonnet 5 pricing for an unrecognized model string
    rather than raising -- a config typo should degrade the estimate, not
    crash extraction."""
    input_price, output_price = _PRICE_PER_TOKEN_USD.get(
        model, _PRICE_PER_TOKEN_USD["claude-sonnet-5"]
    )
    uncached_input = max(usage.input_tokens - usage.cache_read_tokens, 0)
    return (
        uncached_input * input_price
        + usage.cache_read_tokens * input_price * _CACHE_READ_MULTIPLIER
        + usage.output_tokens * output_price
    )


_EXTRACTION_TOOL_NAME = "record_extraction"

# Forced single-tool-call instead of `output_format=`/structured_outputs:
# this org's LLM proxy is Vertex-routed and its allowed-partner-model-features
# policy rejects the `structured_outputs` beta feature for claude-sonnet-5
# (confirmed live: BadRequestError, FAILED_PRECONDITION,
# vertexai.allowedPartnerModelFeatures). Tool use hits none of that -- it's
# not gated by that policy -- and gives the same schema guarantee via
# `tool_choice`.
_EXTRACTION_TOOL = {
    "name": _EXTRACTION_TOOL_NAME,
    "description": "Records the structured facts extracted from the document.",
    "input_schema": ExtractionResult.model_json_schema(),
}

# Empirically, forced tool_choice is non-deterministic in how it fails on a
# small minority of documents -- observed live, same document, different
# malformed shape on each of several consecutive calls: a stringified list
# (schema.py's before-validator already coerces this), literal
# `<parameter name="...">` tool-call XML leaking into a string field, the
# whole payload wrapped under a spurious top-level "parameters" key, and
# multiple *separate* tool_use blocks each holding one item's fields
# flattened instead of one call with nested arrays. Re-running the exact
# same call on a *different* document in that batch, or the same document
# again, was clean far more often than not -- this is sampling variance in
# how the model plans the tool call, not a fixed property of the input
# text. Enumerating every malformed shape and writing a coercion for each
# is a losing game (new shapes keep appearing); retrying the call is not,
# since it's cheap (this batch's documents are short) and each attempt is
# still logged/billed via the accumulated usage returned on success.
_MAX_EXTRACTION_ATTEMPTS = 3


def extract_document(
    document: Document, *, model: str, client: anthropic.Anthropic
) -> tuple[ExtractionResult, ExtractionUsage]:
    """One extraction call for one document, retried up to
    `_MAX_EXTRACTION_ATTEMPTS` times on a malformed tool-call response (see
    the comment above `_MAX_EXTRACTION_ATTEMPTS`). Raises whatever
    `client.messages.create()` raises outright (anthropic.APIStatusError and
    friends are not retried here -- transient-vs-permanent isn't this
    function's call to make) -- the caller (extract/pipeline.py) is
    responsible for catching that per document and logging it, the same way
    ingest/pipeline.py does for normalize/UnsupportedFormatError. Only a
    malformed *response shape* (missing tool_use block, or one that fails
    schema validation) triggers a retry; every attempt's tokens are billed
    and accumulated into the usage returned on eventual success, so cost
    tracking isn't blind to the retries."""
    input_tokens = output_tokens = cache_read_tokens = 0
    last_error: ValueError | ValidationError | None = None

    for attempt in range(1, _MAX_EXTRACTION_ATTEMPTS + 1):
        response = client.messages.create(
            model=model,
            max_tokens=8096,
            system=[
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[{"role": "user", "content": document.raw_text}],
            tools=[_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": _EXTRACTION_TOOL_NAME},
        )
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens
        cache_read_tokens += response.usage.cache_read_input_tokens or 0

        tool_use_block = next(
            (block for block in response.content if block.type == "tool_use"), None
        )
        if tool_use_block is None:
            present_types = [block.type for block in response.content]
            last_error = ValueError(
                f"no tool_use block in response for document {document.id} "
                f"(attempt {attempt}/{_MAX_EXTRACTION_ATTEMPTS}, "
                f"stop_reason={response.stop_reason!r}, block types present={present_types!r})"
            )
            continue

        try:
            result = ExtractionResult.model_validate(tool_use_block.input)
        except ValidationError as exc:
            last_error = exc
            continue

        usage = ExtractionUsage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            attempts=attempt,
        )
        return result, usage

    assert last_error is not None  # loop always sets it before exhausting attempts
    raise last_error
