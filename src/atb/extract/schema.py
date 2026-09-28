"""Structured-extraction output schema.

Asking the model for character offsets directly is unreliable -- LLMs count
characters badly. Instead every extracted item carries a `source_quote`: the
exact verbatim text (copied, not paraphrased) that supports it. Provenance
(document_id + char_start/char_end) is then resolved deterministically in
Python by locating that quote in the document's raw text (see
extract/store.py). An item whose quote can't be found still gets stored --
document_id is provenance enough -- but with a null span, same as any other
nullable char_start/char_end row in models.py.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ActionDirection = Literal["we_owe", "they_owe"]


class ExtractedContact(BaseModel):
    name: str
    email: str | None = None
    title: str | None = None
    is_key_contact: bool = False
    source_quote: str = Field(
        description="Exact verbatim text from the document that names this person."
    )


class ExtractedActionItem(BaseModel):
    description: str
    owner: str | None = None
    direction: ActionDirection = Field(
        description="'we_owe' if our team committed to do this, 'they_owe' if the customer did."
    )
    due_date: str | None = Field(
        default=None, description="ISO 8601 date (YYYY-MM-DD) if a due date was stated, else null."
    )
    source_quote: str = Field(
        description="Exact verbatim text from the document describing this commitment."
    )


class ExtractedDecision(BaseModel):
    description: str
    source_quote: str = Field(
        description="Exact verbatim text from the document recording this decision."
    )


class ExtractedRisk(BaseModel):
    description: str
    source_quote: str = Field(
        description="Exact verbatim text from the document raising this risk or concern."
    )


class ExtractionResult(BaseModel):
    """Top-level schema passed as `output_format` to `client.messages.parse()`.
    Empty lists are the expected, correct answer for a document that has no
    action items/decisions/risks -- the prompt must not be read as requiring
    the model to find something in every category."""

    contacts: list[ExtractedContact] = Field(default_factory=list)
    action_items: list[ExtractedActionItem] = Field(default_factory=list)
    decisions: list[ExtractedDecision] = Field(default_factory=list)
    risks: list[ExtractedRisk] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_stringified_lists(cls, data):
        """Forced tool-use occasionally comes back with a list field encoded
        as a JSON string instead of a native array -- observed on real data
        as both an {"items": [...]}-wrapped string and a bare single-object
        string. Best-effort unwrap those two shapes; anything that isn't
        valid JSON at all (seen once as literal tool-call framing artifacts
        leaking into the field) is left untouched so model_validate still
        raises a clear ValidationError instead of silently inventing data."""
        if not isinstance(data, dict):
            return data
        for field_name in ("contacts", "action_items", "decisions", "risks"):
            value = data.get(field_name)
            if not isinstance(value, str):
                continue
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                data[field_name] = parsed["items"]
            elif isinstance(parsed, dict):
                data[field_name] = [parsed]
            elif isinstance(parsed, list):
                data[field_name] = parsed
        return data
