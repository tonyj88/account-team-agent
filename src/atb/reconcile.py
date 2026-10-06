"""Choose dated evidence and report Salesforce drift without changing source data."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from atb.catalog import Catalog, FieldSpec, load_catalog
from atb.plan import Candidate, Candidates, DriftItem, Evidence, Plan, PlanRow, PlanValue


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _rank(candidate: Candidate) -> tuple:
    priority = {"salesforce": 2, "baseline": 1}
    return candidate.evidence.as_of, priority.get(candidate.evidence.kind, 0)


def _scalar(
    group: list[Candidate],
    spec: FieldSpec,
    cands: Candidates,
    stale_after_days: int,
    approved_baseline: Candidate | None,
) -> tuple[PlanValue, DriftItem | None]:
    humans = [c for c in group if c.evidence.kind == "human"]
    salesforce = [c for c in group if c.evidence.kind == "salesforce"]
    sf = max(salesforce, key=_rank) if salesforce else None
    winner = max(humans or group, key=_rank)
    if not humans and spec.system_of_record and sf is not None:
        winner = sf
    history = sorted((c for c in group if c is not winner), key=_rank, reverse=True)
    approved = bool(humans) or winner is approved_baseline
    reasons: list[str] = []
    flag = None
    drift = None
    if spec.system_of_record and not humans:
        if sf is None:
            reasons.append("no Salesforce value")
        else:
            conflicts = [
                c
                for c in group
                if c.evidence.kind != "salesforce"
                and c.evidence.as_of > sf.evidence.as_of
                and _normalized(c.value or "") != _normalized(sf.value or "")
            ]
            if conflicts:
                conflict = max(conflicts, key=_rank)
                flag = (
                    f"Newer evidence ({conflict.evidence.kind}, {conflict.evidence.as_of}) "
                    f"says: {conflict.value}"
                )
                reasons.append("system-of-record conflict")
    if (
        not spec.system_of_record
        and sf is not None
        and winner.evidence.kind != "salesforce"
        and winner.evidence.as_of > sf.evidence.as_of
        and _normalized(winner.value or "") != _normalized(sf.value or "")
    ):
        reasons.append("newer than Salesforce")
        drift = DriftItem(
            field=spec.key,
            salesforce_value=sf.value or "",
            salesforce_as_of=sf.evidence.as_of,
            salesforce_ref=sf.evidence.ref,
            newer_value=winner.value or "",
            newer_as_of=winner.evidence.as_of,
            newer_ref=winner.evidence.ref,
        )
    if not approved:
        causes = [
            (spec.approval == "needs_approval", "catalog requires approval"),
            (winner.evidence.kind == "llm_draft" or spec.source == "llm_draft", "LLM draft"),
            (winner.confidence == "low", "low confidence"),
            (
                any(_normalized(c.value or "") != _normalized(winner.value or "") for c in history),
                "sources disagree",
            ),
            (
                winner.evidence.as_of < cands.plan_date - timedelta(days=stale_after_days),
                "stale evidence",
            ),
            (winner.evidence.as_of_weak and not spec.system_of_record, "weak as-of date"),
        ]
        reasons.extend(reason for holds, reason in causes if holds)
    return PlanValue(
        value=winner.value,
        status="approved" if approved else "needs_approval" if reasons else "auto",
        reasons=[] if approved else reasons,
        sources=[winner.evidence],
        history=history,
        flag=flag,
    ), drift


def reconcile(
    cands: Candidates,
    baseline: Plan | None = None,
    catalog: Catalog | None = None,
    stale_after_days: int = 182,
) -> Plan:
    """Reconcile scalar evidence and whole rows, preserving untouched baseline values."""
    catalog = catalog if catalog is not None else load_catalog()
    scalars: dict[str, list[Candidate]] = defaultdict(list)
    rows: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for candidate in cands.candidates:
        if candidate.row is None:
            if candidate.field not in catalog.fields:
                raise ValueError(f"Unknown scalar field: {candidate.field}")
            scalars[candidate.field].append(candidate)
        else:
            if candidate.field not in catalog.row_sections:
                raise ValueError(f"Unknown row section: {candidate.field}")
            rows[candidate.field, _normalized(candidate.row_key or "")].append(candidate)
    plan = Plan(
        account=cands.account,
        plan_date=cands.plan_date,
        baseline_date=baseline.plan_date if baseline else None,
    )
    implicit: dict[str, Candidate] = {}
    if baseline is not None:
        for key, value in baseline.fields.items():
            if key not in catalog.fields:
                raise ValueError(f"Unknown scalar field: {key}")
            if key not in scalars:
                plan.fields[key] = value.model_copy(deep=True)
            elif value.status == "approved" and value.value is not None:
                implicit[key] = Candidate(
                    field=key,
                    value=value.value,
                    confidence="high",
                    evidence=Evidence(
                        kind="baseline", as_of=baseline.plan_date, ref="baseline plan"
                    ),
                )
                scalars[key].append(implicit[key])
        for section, baseline_rows in baseline.rows.items():
            if section not in catalog.row_sections:
                raise ValueError(f"Unknown row section: {section}")
            for row in baseline_rows:
                if row.status == "approved" and (section, _normalized(row.row_key)) not in rows:
                    plan.rows.setdefault(section, []).append(row.model_copy(deep=True))
    for key, group in scalars.items():
        value, drift = _scalar(
            group, catalog.fields[key], cands, stale_after_days, implicit.get(key)
        )
        plan.fields[key] = value
        if drift is not None:
            plan.drift.append(drift)
    for (section, _), group in rows.items():
        winner = max(group, key=_rank)
        cells = dict(winner.row or {})
        reasons = []
        if any(
            cells.get(col.key, "").strip()
            and (col.approval == "needs_approval" or col.source == "llm_draft")
            for col in catalog.row_sections[section].columns
        ):
            reasons.append("catalog requires approval")
        if winner.confidence == "low":
            reasons.append("low confidence")
        plan.rows.setdefault(section, []).append(
            PlanRow(
                row_key=winner.row_key or "",
                cells=cells,
                status="needs_approval" if reasons else "auto",
                reasons=reasons,
                sources=[winner.evidence],
            )
        )
    for section_rows in plan.rows.values():
        section_rows.sort(key=lambda row: _normalized(row.row_key))
    return plan


def _markdown(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .replace("\r", "<br>")
    )


def drift_markdown(plan: Plan) -> str:
    """Render the dated Salesforce drift report using default catalog labels."""
    lines = [f"# Salesforce drift — {_markdown(plan.account)} — {plan.plan_date}", ""]
    if not plan.drift:
        return "\n".join([*lines, "No Salesforce drift.", ""])
    catalog = load_catalog()
    lines.extend(
        [
            "| Field | Salesforce value | As-of | Ref | Newer value | As-of | Ref |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in plan.drift:
        spec = catalog.fields.get(item.field)
        cells = [
            spec.label if spec else item.field,
            item.salesforce_value,
            item.salesforce_as_of.isoformat(),
            item.salesforce_ref,
            item.newer_value,
            item.newer_as_of.isoformat(),
            item.newer_ref,
        ]
        lines.append("| " + " | ".join(_markdown(cell) for cell in cells) + " |")
    return "\n".join(lines) + "\n"
