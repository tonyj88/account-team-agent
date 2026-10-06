"""Data contract between the /account-plan skill and the toolkit.

The skill writes `candidates.json` (every candidate value with its dated evidence).
`reconcile` turns it into `plan.json`; `validate` checks it; `render` fills the .docx.
Both files are customer data and live under data/ (gitignored).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SourceKind = Literal[
    "salesforce",  # ref = "<Object>/<RecordId>/<Field>"
    "email",
    "transcript",
    "teams_chat",
    "sharepoint",
    "confluence",
    "note",  # local Obsidian/Markdown side note
    "calendar",
    "baseline",  # last approved plan; as_of = its approval date
    "human",  # a decision recorded by Tony; always wins
    "llm_draft",  # Claude's judgement (R/A/G, position); always needs approval
]

# Sources whose evidence must carry a verbatim quote from a saved text file.
TEXT_KINDS: frozenset[str] = frozenset(
    {"email", "transcript", "teams_chat", "sharepoint", "confluence", "note"}
)

Confidence = Literal["high", "medium", "low"]
Status = Literal["auto", "needs_approval", "approved"]


class Evidence(BaseModel):
    kind: SourceKind
    as_of: date
    ref: str = Field(description="SF Object/Id/Field, a URL, or a local path")
    quote: str | None = None
    text_file: str | None = Field(
        default=None, description="Saved source text, relative to the plan directory"
    )
    speaker: str | None = None
    speaker_side: Literal["customer", "internal"] | None = None
    timestamp: str | None = None  # "HH:MM:SS" inside a transcript
    as_of_weak: bool = Field(
        default=False, description="True when as_of is a fallback such as LastModifiedDate"
    )


class Candidate(BaseModel):
    """One proposed value for a scalar field, or one proposed row in a table."""

    field: str = Field(description="Scalar field key, or a row-section key such as 'risks'")
    value: str | None = None
    row_key: str | None = Field(default=None, description="Identity of the row, e.g. a name")
    row: dict[str, str] | None = None
    confidence: Confidence = "medium"
    evidence: Evidence

    @model_validator(mode="after")
    def _scalar_or_row(self) -> Candidate:
        if (self.value is None) == (self.row is None):
            raise ValueError("a candidate has exactly one of `value` or `row`")
        if self.row is not None and not self.row_key:
            raise ValueError("a row candidate needs `row_key`")
        return self


class Candidates(BaseModel):
    account: str
    plan_date: date
    candidates: list[Candidate]


class PlanValue(BaseModel):
    value: str | None
    status: Status
    reasons: list[str] = Field(default_factory=list, description="Why it needs approval")
    sources: list[Evidence] = Field(default_factory=list, description="Winning evidence")
    history: list[Candidate] = Field(default_factory=list, description="Older or losing values")
    flag: str | None = Field(
        default=None, description="System-of-record conflict, shown next to the value"
    )


class PlanRow(BaseModel):
    row_key: str
    cells: dict[str, str]
    status: Status
    reasons: list[str] = Field(default_factory=list)
    sources: list[Evidence] = Field(default_factory=list)


class DriftItem(BaseModel):
    """A field where newer non-Salesforce evidence contradicts Salesforce."""

    field: str
    salesforce_value: str
    salesforce_as_of: date
    salesforce_ref: str
    newer_value: str
    newer_as_of: date
    newer_ref: str


class Plan(BaseModel):
    account: str
    plan_date: date
    baseline_date: date | None = None
    fields: dict[str, PlanValue] = Field(default_factory=dict)
    rows: dict[str, list[PlanRow]] = Field(default_factory=dict)
    drift: list[DriftItem] = Field(default_factory=list)
