"""Deterministic checks for plan evidence, approval and secret hygiene."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from atb.catalog import Catalog, load_catalog
from atb.plan import TEXT_KINDS, Evidence, Plan, PlanRow, PlanValue
from atb.redact import redact_text

_SALESFORCE_REF = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*/[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?/"
    r"[A-Za-z_][A-Za-z0-9_]*"
)


@dataclass(frozen=True)
class Issue:
    """One validation error or advisory warning."""

    level: Literal["error", "warning"]
    where: str
    message: str


def validate(plan: Plan, plan_dir: Path, catalog: Catalog | None = None) -> list[Issue]:
    """Check a plan against its catalog and locally saved evidence."""
    catalog = catalog if catalog is not None else load_catalog()
    root = plan_dir.resolve()
    issues: list[Issue] = []
    texts: dict[Path, str | None] = {}

    def error(where: str, message: str) -> None:
        issues.append(Issue("error", where, message))

    def scan(text: str | None, where: str, label: str) -> None:
        if text is None:
            return
        for finding in redact_text(text).findings:
            error(where, f"secret in {label}: {finding.rule} at line {finding.line_number}")

    def evidence(source: Evidence, where: str) -> None:
        scan(source.quote, where, "quote")
        if source.kind == "salesforce" and not _SALESFORCE_REF.fullmatch(source.ref):
            error(where, "invalid salesforce ref: expected <Object>/<Id>/<Field>")
        quote = " ".join((source.quote or "").split())
        if source.kind in TEXT_KINDS:
            if not quote:
                error(where, "text evidence requires quote")
            if not source.text_file:
                error(where, "text evidence requires text_file")
        if not source.text_file:
            return
        relative = Path(source.text_file)
        try:
            path = (root / relative).resolve()
        except (OSError, RuntimeError, ValueError):
            error(where, "invalid text_file path")
            return
        if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
            error(where, "text_file must stay inside plan_dir")
            return
        if path not in texts:
            try:
                texts[path] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError, ValueError):
                texts[path] = None
            else:
                scan(texts[path], str(path), "text file")
        text = texts[path]
        if text is None:
            error(where, "text_file missing or unreadable")
        elif source.kind in TEXT_KINDS and quote and quote not in " ".join(text.split()):
            error(where, "quote not found verbatim")

    def entry(item: PlanValue | PlanRow, where: str, needs_approval: bool) -> None:
        values = [item.value] if isinstance(item, PlanValue) else list(item.cells.values())
        if any(value and value.strip() for value in values) and not item.sources:
            error(where, "non-empty value requires at least one source")
        for value in values:
            scan(value, where, "value" if isinstance(item, PlanValue) else "cell")
        if item.status == "auto" and (
            needs_approval or any(source.kind == "llm_draft" for source in item.sources)
        ):
            error(where, "should need approval")
        if item.status == "approved" and not any(
            source.kind in {"human", "baseline"} for source in item.sources
        ):
            error(where, "only a human can approve")
        for source in item.sources:
            evidence(source, where)

    for key, value in plan.fields.items():
        spec = catalog.fields.get(key)
        if spec is None:
            error(key, "unknown field key")
        entry(
            value,
            key,
            spec is not None and (spec.approval == "needs_approval" or spec.source == "llm_draft"),
        )
        for candidate in value.history:
            scan(candidate.value, key, "history value")
            for cell in (candidate.row or {}).values():
                scan(cell, key, "history cell")
            evidence(candidate.evidence, key)
    for key, rows in plan.rows.items():
        section = catalog.row_sections.get(key)
        if section is None:
            error(f"rows.{key}", "unknown row-section key")
        for row in rows:
            needs_approval = section is not None and any(
                row.cells.get(column.key, "").strip()
                and (column.approval == "needs_approval" or column.source == "llm_draft")
                for column in section.columns
            )
            entry(row, f"rows.{key}[{row.row_key}]", needs_approval)
    for drift in plan.drift:
        scan(drift.salesforce_value, drift.field, "drift salesforce value")
        scan(drift.newer_value, drift.field, "drift newer value")
    for spec in catalog.mvp_fields():
        if spec.source not in {"human", "system", "derived"} and spec.key not in plan.fields:
            issues.append(Issue("warning", spec.key, "MVP field empty"))
    return sorted(issues, key=lambda issue: (issue.level != "error", issue.where))
