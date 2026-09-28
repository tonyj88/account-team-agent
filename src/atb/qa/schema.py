"""QA structured-output schemas: question routing and answer synthesis.

Same provenance discipline as extract/schema.py -- `Citation.quote` is
resolved deterministically against the cited Document.raw_text in Python
(see pipeline.py), never trusted as an LLM-reported char span.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

QuestionCategory = Literal["structured", "synthesis", "unsupported_crm"]


class RoutingDecision(BaseModel):
    category: QuestionCategory = Field(
        description=(
            "'structured' if answerable by looking up contacts, action items, "
            "decisions, or risks already recorded for the account. 'synthesis' "
            "if it requires reading and summarizing meeting notes beyond those "
            "structured facts. 'unsupported_crm' if it asks about renewal date, "
            "contract terms, or open support/case status -- data this system "
            "does not have access to."
        )
    )
    reason: str


class Citation(BaseModel):
    document_id: int
    quote: str = Field(
        description="Exact verbatim text from the cited document supporting the claim."
    )
    char_start: int | None = None
    char_end: int | None = None


class Answer(BaseModel):
    can_answer: bool = Field(
        description=(
            "False if the available data (structured facts + retrieved notes) does "
            "not contain enough information to answer -- including anything "
            "CRM-backed like renewal date or support cases. Never guess when False."
        )
    )
    answer_text: str = Field(
        description="The answer, or a short explanation of why it can't be answered."
    )
    citations: list[Citation] = Field(default_factory=list)
