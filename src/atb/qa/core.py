"""LLM calls for QA: question routing (Haiku) and answer synthesis (Sonnet).

Both use forced tool-use, not `client.messages.parse(output_format=...)` --
this org's Anthropic access is Vertex-proxied and its
`allowedPartnerModelFeatures` policy rejects the `structured_outputs` beta
feature (confirmed live in Phase 3, see extract/core.py). Tool use isn't
gated by that policy.
"""

from __future__ import annotations

import anthropic

from atb.extract.core import ExtractionUsage
from atb.qa.retrieval import RetrievedChunk
from atb.qa.schema import Answer, RoutingDecision

_ROUTING_SYSTEM_PROMPT = """\
You route a question about a customer account into exactly one category:

- "structured": answerable by looking up contacts, action items, decisions, \
or risks already recorded for the account (e.g. "who are the key contacts", \
"what do we owe them", "any open risks").
- "synthesis": requires reading and summarizing meeting notes beyond those \
structured facts (e.g. "what's the state of the migration project", \
"summarize our last call").
- "unsupported_crm": asks about renewal date, contract terms, pricing, or \
open support/case status -- data this system does not have access to \
(e.g. "when does their contract renew", "how many open support cases do \
they have").

Pick the single best-fitting category."""

_ROUTING_TOOL_NAME = "record_routing_decision"
_ROUTING_TOOL = {
    "name": _ROUTING_TOOL_NAME,
    "description": "Records the routing decision for a question.",
    "input_schema": RoutingDecision.model_json_schema(),
}

_ANSWER_SYSTEM_PROMPT = """\
You answer a question about a customer account using only the structured \
facts and retrieved note excerpts provided in the user message. \
Cite only from that provided context -- never from general knowledge or \
assumption. If the question asks about data not present in the provided \
context (for example CRM-backed data like renewal date, contract terms, or \
support case status), set can_answer to false and say so explicitly rather \
than guessing. Every citation's `quote` must be copied verbatim from the \
cited document's context, same whitespace and casing -- do not paraphrase \
it, since an inexact quote loses its citation.

Never copy a credential, password, token, or API key into the answer text \
or into a citation quote, even if one appears in the provided context. \
Redaction of the source notes happens upstream of this call; this is a \
defense-in-depth instruction, not the primary control."""

_ANSWER_TOOL_NAME = "record_answer"
_ANSWER_TOOL = {
    "name": _ANSWER_TOOL_NAME,
    "description": "Records the answer to the account question.",
    "input_schema": Answer.model_json_schema(),
}


def _usage_from_response(model: str, response) -> ExtractionUsage:
    return ExtractionUsage(
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_read_tokens=response.usage.cache_read_input_tokens or 0,
    )


def route_question(
    question: str, *, model: str, client: anthropic.Anthropic
) -> tuple[RoutingDecision, ExtractionUsage]:
    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=_ROUTING_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
        tools=[_ROUTING_TOOL],
        tool_choice={"type": "tool", "name": _ROUTING_TOOL_NAME},
    )
    tool_use_block = next(block for block in response.content if block.type == "tool_use")
    decision = RoutingDecision.model_validate(tool_use_block.input)
    return decision, _usage_from_response(model, response)


def _format_chunks(retrieved_chunks: list[RetrievedChunk]) -> str:
    if not retrieved_chunks:
        return "(no note excerpts retrieved)"
    parts = []
    for r in retrieved_chunks:
        parts.append(
            f"[document_id={r.chunk.document_id}]\n{r.chunk.text}"
        )
    return "\n\n".join(parts)


def answer_question(
    question: str,
    *,
    account_name: str | None,
    structured_context: str,
    retrieved_chunks: list[RetrievedChunk],
    model: str,
    client: anthropic.Anthropic,
) -> tuple[Answer, ExtractionUsage]:
    account_line = account_name or "(no account resolved)"
    user_content = (
        f"Account: {account_line}\n\n"
        f"Structured facts:\n{structured_context}\n\n"
        f"Retrieved note excerpts:\n{_format_chunks(retrieved_chunks)}\n\n"
        f"Question: {question}"
    )
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=[
            {"type": "text", "text": _ANSWER_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user_content}],
        tools=[_ANSWER_TOOL],
        tool_choice={"type": "tool", "name": _ANSWER_TOOL_NAME},
    )
    tool_use_block = next(block for block in response.content if block.type == "tool_use")
    answer = Answer.model_validate(tool_use_block.input)
    return answer, _usage_from_response(model, response)
