"""Synthetic freshness, approval, row and drift-report examples."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from atb.plan import Candidate, Candidates, Evidence, Plan, PlanRow, PlanValue
from atb.reconcile import drift_markdown, reconcile

TODAY = date(2026, 10, 6)
OWNER = "snapshot.account_owner"


def candidate(value="Jane Doe", kind="salesforce", days=0, field=OWNER, **kwargs):
    weak = kwargs.pop("weak", False)
    return Candidate(
        field=field,
        value=value,
        evidence=Evidence(
            kind=kind, as_of=TODAY - timedelta(days=days), ref=f"{kind}/synthetic", as_of_weak=weak
        ),
        **kwargs,
    )


def bundle(*items):
    return Candidates(account="Acme Corp", plan_date=TODAY, candidates=list(items))


def test_newer_email_drifts_and_older_email_loses():
    sf = candidate(days=20)
    email = candidate("Alex Doe", "email", days=1)
    plan = reconcile(bundle(sf, email))
    assert plan.fields[OWNER].value == "Alex Doe"
    assert plan.fields[OWNER].status == "needs_approval"
    assert plan.fields[OWNER].reasons == ["newer than Salesforce", "sources disagree"]
    assert plan.fields[OWNER].history == [sf]
    assert len(plan.drift) == 1
    older = reconcile(bundle(candidate(), candidate("Alex Doe", "email", days=30)))
    assert older.fields[OWNER].value == "Jane Doe"
    assert older.drift == []
    assert older.fields[OWNER].history[0].evidence.kind == "email"


def test_system_of_record_conflict_and_weak_exemption():
    field = "snapshot.renewal_dates"
    plan = reconcile(
        bundle(
            candidate("2027-01-01", days=20, field=field),
            candidate("2027-04-01", "email", field=field),
        )
    )
    value = plan.fields[field]
    assert value.value == "2027-01-01"
    assert value.status == "needs_approval"
    assert "system-of-record conflict" in value.reasons
    assert value.flag == "Newer evidence (email, 2026-10-06) says: 2027-04-01"
    assert not plan.drift
    arr = reconcile(bundle(candidate("150000", field="snapshot.current_arr", weak=True)))
    assert arr.fields["snapshot.current_arr"].status == "auto"


def test_humans_win_even_for_system_of_record():
    for field in (OWNER, "snapshot.current_arr"):
        plan = reconcile(
            bundle(
                candidate("Older human", "human", days=30, field=field),
                candidate("Newest human", "human", days=20, field=field),
                candidate("SF", field=field),
            )
        )
        assert plan.fields[field].value == "Newest human"
        assert plan.fields[field].status == "approved"
        assert plan.fields[field].reasons == []


@pytest.mark.parametrize("kind", ["salesforce", "llm_draft"])
def test_catalog_draft_always_requires_approval(kind):
    plan = reconcile(bundle(candidate("Amber", kind, field="snapshot.health_rag")))
    assert plan.fields["snapshot.health_rag"].reasons == ["catalog requires approval", "LLM draft"]


@pytest.mark.parametrize("days, expected", [(182, "auto"), (183, "needs_approval")])
def test_staleness_boundary(days, expected):
    value = reconcile(bundle(candidate(days=days))).fields[OWNER]
    assert value.status == expected
    assert ("stale evidence" in value.reasons) == (days > 182)


def test_baseline_carry_forward_and_implicit_candidate():
    baseline = Plan(
        account="Acme Corp",
        plan_date=TODAY - timedelta(days=10),
        fields={
            OWNER: PlanValue(value="Jane Doe", status="approved"),
        },
    )
    original = baseline.model_dump()
    carry = reconcile(bundle(), baseline)
    assert carry.fields[OWNER] == baseline.fields[OWNER]
    assert carry.fields[OWNER] is not baseline.fields[OWNER]
    assert carry.baseline_date == baseline.plan_date
    retained = reconcile(bundle(candidate("Alex Doe", "email", days=20)), baseline)
    assert retained.fields[OWNER].status == "approved"
    assert retained.fields[OWNER].sources[0].kind == "baseline"
    replaced = reconcile(bundle(candidate("Alex Doe", "email")), baseline)
    assert replaced.fields[OWNER].value == "Alex Doe"
    assert replaced.fields[OWNER].status == "needs_approval"
    assert baseline.model_dump() == original


@pytest.mark.parametrize("row", [None, {"name": "Jane Doe"}])
def test_unknown_keys_fail(row):
    item = Candidate(
        field="snapshot.typo",
        value="Jane Doe" if row is None else None,
        row=row,
        row_key="Jane Doe" if row is not None else None,
        evidence=Evidence(kind="note", as_of=TODAY, ref="synthetic"),
    )
    with pytest.raises(ValueError, match="snapshot.typo"):
        reconcile(bundle(item))


def row(key="Jane Doe", days=0, kind="note", **cells):
    return Candidate(
        field="stakeholders",
        row_key=key,
        row=cells,
        evidence=Evidence(kind=kind, as_of=TODAY - timedelta(days=days), ref="synthetic"),
    )


def test_row_grouping_whole_row_sort_and_approval():
    plan = reconcile(
        bundle(
            row(" JANE   DOE ", days=10, name="Jane Doe", coverage="Old"),
            row("jane doe", name="Jane Doe", position="Advocate"),
            row("Alex Doe", name="Alex Doe", position=" "),
        )
    )
    result = plan.rows["stakeholders"]
    assert [r.row_key for r in result] == ["Alex Doe", "jane doe"]
    assert result[0].status == "auto"
    assert result[1].cells == {"name": "Jane Doe", "position": "Advocate"}
    assert result[1].reasons == ["catalog requires approval"]


def test_approved_baseline_rows_only_carry_when_untouched():
    baseline = Plan(
        account="Acme Corp",
        plan_date=TODAY,
        rows={
            "stakeholders": [
                PlanRow(row_key="Jane Doe", cells={"name": "Jane Doe"}, status="approved"),
                PlanRow(row_key="Alex Doe", cells={"name": "Alex Doe"}, status="auto"),
            ]
        },
    )
    assert len(reconcile(bundle(), baseline).rows["stakeholders"]) == 1
    refreshed = reconcile(bundle(row("JANE DOE", name="Jane Doe")), baseline)
    assert refreshed.rows["stakeholders"][0].status == "auto"


def test_date_ties_and_normalized_values():
    email = candidate(" jane   DOE ", "email")
    sf = candidate()
    plan = reconcile(bundle(email, sf))
    assert plan.fields[OWNER].sources == [sf.evidence]
    assert plan.fields[OWNER].status == "auto"
    assert not reconcile(bundle(sf, candidate(" jane   DOE ", "email", days=-1))).drift
    first = candidate("First", "note")
    assert reconcile(bundle(first, candidate("Second", "email"))).fields[OWNER].value == "First"


def test_low_confidence_weak_dates_and_missing_salesforce():
    value = reconcile(bundle(candidate(confidence="low", weak=True))).fields[OWNER]
    assert value.reasons == ["low confidence", "weak as-of date"]
    value = reconcile(bundle(candidate("150000", "email", field="snapshot.current_arr")))
    assert value.fields["snapshot.current_arr"].reasons == ["no Salesforce value"]
    item = row(name="Jane Doe").model_copy(update={"confidence": "low"})
    assert reconcile(bundle(item)).rows["stakeholders"][0].reasons == ["low confidence"]


def test_drift_markdown_with_and_without_items():
    empty = drift_markdown(reconcile(bundle()))
    assert "Acme Corp" in empty and "2026-10-06" in empty
    assert "No Salesforce drift." in empty
    plan = reconcile(bundle(candidate(days=20), candidate("Alex | Doe\nNew", "email")))
    report = drift_markdown(plan)
    assert "Account Owner" in report
    assert "Jane Doe | 2026-09-16 | salesforce/synthetic" in report
    assert "Alex \\| Doe<br>New | 2026-10-06 | email/synthetic" in report
    assert len([line for line in report.splitlines() if line.startswith("| Account Owner")]) == 1
