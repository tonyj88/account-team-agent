"""Field catalog: loads config/account_plan_fields.yaml into typed specs.

The catalog is the single list of plan fields. Reconcile, validate and render all
look fields up here instead of hard-coding keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "account_plan_fields.yaml"

# Sources whose value is a human judgement or an LLM draft; never auto-approved.
DRAFT_SOURCES = {"llm_draft"}


@dataclass(frozen=True)
class FieldSpec:
    """One scalar field, e.g. `snapshot.account_owner`."""

    key: str
    label: str
    section: str
    source: str
    approval: str  # "auto" | "needs_approval"
    mvp: bool
    system_of_record: bool = False


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str
    source: str
    approval: str


@dataclass(frozen=True)
class RowSectionSpec:
    """A repeating table, e.g. `stakeholders`, `risks`, `action_plan`."""

    key: str
    title: str
    mvp: bool
    columns: tuple[ColumnSpec, ...]


@dataclass(frozen=True)
class Catalog:
    fields: dict[str, FieldSpec]
    row_sections: dict[str, RowSectionSpec]
    refresh_policy: dict = field(default_factory=dict)

    def mvp_fields(self) -> list[FieldSpec]:
        return [f for f in self.fields.values() if f.mvp]

    def mvp_row_sections(self) -> list[RowSectionSpec]:
        return [r for r in self.row_sections.values() if r.mvp]


def _field(raw: dict, section: str, mvp: bool) -> FieldSpec:
    return FieldSpec(
        key=raw["key"],
        label=raw["label"],
        section=section,
        source=raw.get("source", "note"),
        approval=raw.get("approval", "auto"),
        mvp=mvp,
        system_of_record=bool(raw.get("system_of_record", False)),
    )


@cache
def load_catalog(path: Path = DEFAULT_PATH) -> Catalog:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    fields: dict[str, FieldSpec] = {}
    rows: dict[str, RowSectionSpec] = {}

    header = data.get("header", {})
    for raw in header.get("fields", []):
        f = _field(raw, "header", bool(header.get("mvp")))
        fields[f.key] = f

    for sec in data.get("sections", []):
        mvp = bool(sec.get("mvp"))
        for raw in sec.get("fields", []):
            f = _field(raw, sec["key"], mvp)
            fields[f.key] = f
        # MEDDPICC: each element has an evidence field and an R/A/G draft field.
        element_fields = sec.get("element_fields", {})
        for el in sec.get("elements", []):
            for suffix, spec in element_fields.items():
                key = f"{el['key']}.{suffix}"
                fields[key] = FieldSpec(
                    key=key,
                    label=el["label"],
                    section=sec["key"],
                    source=spec.get("source", "note"),
                    approval=spec.get("approval", "auto"),
                    mvp=mvp,
                )
        if sec.get("kind") == "rows":
            cols = tuple(
                ColumnSpec(
                    key=c["key"],
                    label=c["label"],
                    source=c.get("source", "note"),
                    approval=c.get("approval", "auto"),
                )
                for c in sec.get("columns", [])
            )
            rows[sec["key"]] = RowSectionSpec(
                key=sec["key"], title=sec["title"], mvp=mvp, columns=cols
            )

    return Catalog(fields=fields, row_sections=rows, refresh_policy=data.get("refresh_policy", {}))
