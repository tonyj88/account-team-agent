"""Checks use only synthetic plans and locally generated evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from atb.catalog import Catalog, ColumnSpec, FieldSpec, RowSectionSpec
from atb.plan import Candidate, Evidence, Plan, PlanRow, PlanValue
from atb.validate import Issue, validate

DAY = date(2026, 10, 1)


@pytest.fixture
def catalog() -> Catalog:
    field = FieldSpec("summary", "Summary", "snapshot", "note", "auto", True)
    column = ColumnSpec("name", "Name", "human", "auto")
    section = RowSectionSpec("stakeholders", "Stakeholders", False, (column,))
    return Catalog({field.key: field}, {section.key: section})


@pytest.fixture
def plan(tmp_path: Path) -> Plan:
    (tmp_path / "note.txt").write_text("Acme Corp  needs\n better scans.", encoding="utf-8")
    source = Evidence(
        kind="note",
        as_of=DAY,
        ref="note",
        text_file="note.txt",
        quote="Acme Corp needs better scans.",
    )
    return Plan(
        account="Acme Corp",
        plan_date=DAY,
        fields={"summary": PlanValue(value="Better scans", status="auto", sources=[source])},
    )


def messages(plan: Plan, tmp_path: Path, catalog: Catalog) -> list[str]:
    return [issue.message for issue in validate(plan, tmp_path, catalog)]


def test_clean_plan(plan: Plan, tmp_path: Path, catalog: Catalog):
    assert validate(plan, tmp_path, catalog) == []


@pytest.mark.parametrize(
    ("attribute", "value", "expected"),
    [
        ("quote", "Acme Corp wants improved scanning.", "quote not found verbatim"),
        ("quote", "acme Corp needs better scans.", "quote not found verbatim"),
        ("quote", "  ", "text evidence requires quote"),
        ("text_file", None, "text evidence requires text_file"),
        ("text_file", "missing.txt", "text_file missing or unreadable"),
        ("text_file", "../outside.txt", "text_file must stay inside plan_dir"),
    ],
)
def test_invalid_text_evidence(plan, tmp_path, catalog, attribute, value, expected):
    setattr(plan.fields["summary"].sources[0], attribute, value)
    assert expected in messages(plan, tmp_path, catalog)


@pytest.mark.parametrize("kind", ["absolute", "symlink"])
def test_unsafe_path(plan, tmp_path, catalog, kind):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("Acme Corp needs better scans.", encoding="utf-8")
    if kind == "symlink":
        (tmp_path / "link.txt").symlink_to(outside)
        path = "link.txt"
    else:
        path = str(outside)
    plan.fields["summary"].sources[0].text_file = path
    assert "text_file must stay inside plan_dir" in messages(plan, tmp_path, catalog)


@pytest.mark.parametrize(
    "ref",
    ["Account/bad/Name", "Account/" + "a" * 16 + "/Name", "Account/" + "a" * 15 + "/Name/extra"],
)
def test_bad_salesforce_ref(plan, tmp_path, catalog, ref):
    plan.fields["summary"].sources = [Evidence(kind="salesforce", as_of=DAY, ref=ref)]
    assert any("invalid salesforce ref" in m for m in messages(plan, tmp_path, catalog))


@pytest.mark.parametrize("length", [15, 18])
def test_valid_salesforce_ref(plan, tmp_path, catalog, length):
    plan.fields["summary"].sources = [
        Evidence(kind="salesforce", as_of=DAY, ref=f"Account/{'a' * length}/Name")
    ]
    assert validate(plan, tmp_path, catalog) == []


@pytest.mark.parametrize("rule", ["evidence", "catalog_source", "catalog_approval"])
def test_auto_draft(plan, tmp_path, catalog, rule):
    if rule == "evidence":
        plan.fields["summary"].sources = [Evidence(kind="llm_draft", as_of=DAY, ref="draft")]
    else:
        field = catalog.fields["summary"]
        catalog.fields["summary"] = replace(
            field,
            **{
                "source" if rule == "catalog_source" else "approval": "llm_draft"
                if rule == "catalog_source"
                else "needs_approval"
            },
        )
    assert "should need approval" in messages(plan, tmp_path, catalog)


def test_approved_requires_human(plan, tmp_path, catalog):
    plan.fields["summary"].status = "approved"
    assert "only a human can approve" in messages(plan, tmp_path, catalog)


@pytest.mark.parametrize("kind", ["human", "baseline"])
def test_approved_human_or_baseline(plan, tmp_path, catalog, kind):
    plan.fields["summary"].status = "approved"
    plan.fields["summary"].sources = [Evidence(kind=kind, as_of=DAY, ref="review")]
    assert validate(plan, tmp_path, catalog) == []


@pytest.mark.parametrize("location", ["quote", "value", "cell", "file", "history"])
def test_secret_is_reported_without_leaking(plan, tmp_path, catalog, location):
    secret = "x1N2IN#7x9OI"
    text = f"pw: {secret}"
    if location == "quote":
        plan.fields["summary"].sources[0].quote = text
    elif location == "value":
        plan.fields["summary"].value = text
    elif location == "cell":
        plan.rows["stakeholders"] = [
            PlanRow(row_key="Jane Doe", cells={"name": text}, status="needs_approval")
        ]
    elif location == "file":
        with (tmp_path / "note.txt").open("a", encoding="utf-8") as stream:
            stream.write("\n" + text)
    else:
        plan.fields["summary"].history = [
            Candidate(field="summary", value=text, evidence=plan.fields["summary"].sources[0])
        ]
    issues = validate(plan, tmp_path, catalog)
    assert any("pw_label_line at line" in issue.message for issue in issues)
    assert all(secret not in issue.message for issue in issues)


def test_mvp_missing_warning(tmp_path, catalog):
    plan = Plan(account="Acme Corp", plan_date=DAY)
    assert validate(plan, tmp_path, catalog) == [Issue("warning", "summary", "MVP field empty")]
    for source in ("human", "system", "derived"):
        catalog.fields["summary"] = replace(catalog.fields["summary"], source=source)
        assert validate(plan, tmp_path, catalog) == []


def test_unknown_and_unsourced_entries_are_sorted(plan, tmp_path, catalog):
    plan.fields = {"z_unknown": PlanValue(value="Some value", status="auto")}
    plan.rows = {
        "unknown": [PlanRow(row_key="Jane Doe", cells={"name": "Jane Doe"}, status="auto")]
    }
    issues = validate(plan, tmp_path, catalog)
    assert any(issue.message == "unknown field key" for issue in issues)
    assert any(issue.message == "unknown row-section key" for issue in issues)
    assert sum("requires at least one source" in issue.message for issue in issues) == 2
    assert issues == sorted(issues, key=lambda issue: (issue.level != "error", issue.where))


def test_row_approval_from_present_column(plan, tmp_path, catalog):
    column = ColumnSpec("name", "Name", "llm_draft", "auto")
    catalog.row_sections["stakeholders"] = replace(
        catalog.row_sections["stakeholders"], columns=(column,)
    )
    plan.rows["stakeholders"] = [
        PlanRow(
            row_key="Jane Doe",
            cells={"name": "Jane Doe"},
            status="auto",
            sources=[Evidence(kind="human", as_of=DAY, ref="review")],
        )
    ]
    assert Issue("error", "rows.stakeholders[Jane Doe]", "should need approval") in validate(
        plan, tmp_path, catalog
    )


def test_text_file_read_once(plan, tmp_path, catalog, monkeypatch):
    original = Path.read_text
    reads = []

    def read(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    plan.fields["summary"].sources.append(
        plan.fields["summary"].sources[0].model_copy(update={"text_file": "./note.txt"})
    )
    assert validate(plan, tmp_path, catalog) == []
    assert reads == [(tmp_path / "note.txt").resolve()]


def test_empty_approval_cell_does_not_require_approval(tmp_path: Path) -> None:
    plan = Plan(
        account="Acme Corp",
        plan_date=date(2026, 10, 1),
        rows={
            "stakeholders": [
                PlanRow(
                    row_key="Jane Doe",
                    cells={"name": "Jane Doe", "position": ""},
                    status="auto",
                    sources=[
                        Evidence(
                            kind="salesforce",
                            as_of=date(2026, 9, 1),
                            ref="Contact/003000000000001AAA/Name",
                        )
                    ],
                )
            ]
        },
    )
    assert not [i for i in validate(plan, tmp_path) if i.level == "error"]
