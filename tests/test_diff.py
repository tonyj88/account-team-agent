from datetime import date

from atb.diff import diff_markdown, diff_plans
from atb.plan import Plan, PlanRow, PlanValue


def test_diff_added_changed_removed_and_empty():
    old = Plan(
        account="Acme Corp",
        plan_date=date(2026, 1, 1),
        fields={
            "keep": PlanValue(value="same", status="auto"),
            "change": PlanValue(value="before", status="auto"),
            "remove": PlanValue(value="gone", status="auto"),
        },
        rows={
            "risks": [
                PlanRow(
                    row_key="security", cells={"status": "open", "owner": "Jane Doe"}, status="auto"
                )
            ]
        },
    )
    new = Plan(
        account="Acme Corp",
        plan_date=date(2026, 2, 1),
        fields={
            "keep": PlanValue(value="same", status="auto"),
            "change": PlanValue(value="after", status="auto"),
            "add": PlanValue(value="new", status="auto"),
        },
        rows={
            "risks": [
                PlanRow(
                    row_key="security",
                    cells={"status": "closed", "owner": "Jane Doe"},
                    status="auto",
                ),
                PlanRow(row_key="new", cells={"status": "open"}, status="auto"),
            ]
        },
    )
    changes = diff_plans(new, old)
    assert [(c.kind, c.where) for c in changes] == [
        ("added", "add"),
        ("changed", "change"),
        ("removed", "remove"),
        ("added", "rows.risks[new]"),
        ("changed", "rows.risks[security].status"),
    ]
    assert "| Change | Field / row | Old | New |" in diff_markdown(changes)
    assert diff_plans(new, new) == []
    assert diff_markdown([]) == "No changes since the baseline."
