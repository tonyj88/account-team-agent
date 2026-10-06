"""Compare account plans with an optional approved baseline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from atb.plan import Plan


@dataclass(frozen=True)
class Change:
    """One scalar or row-cell change between plans."""

    kind: Literal["added", "changed", "removed"]
    where: str
    old: str | None
    new: str | None


def _row_text(row: dict[str, str]) -> str:
    return "; ".join(f"{key}={row[key]}" for key in sorted(row))


def diff_plans(new: Plan, old: Plan | None) -> list[Change]:
    """Compare plan values and row cells against the baseline."""
    if old is None:
        old = Plan(account=new.account, plan_date=new.plan_date)
    changes: list[Change] = []
    for key in sorted(set(new.fields) | set(old.fields)):
        before = old.fields.get(key).value if key in old.fields else None
        after = new.fields.get(key).value if key in new.fields else None
        if before != after:
            kind = "added" if before is None else "removed" if after is None else "changed"
            changes.append(Change(kind, key, before, after))
    for section in sorted(set(new.rows) | set(old.rows)):
        before_rows = {row.row_key: row.cells for row in old.rows.get(section, [])}
        after_rows = {row.row_key: row.cells for row in new.rows.get(section, [])}
        for row_key in sorted(set(before_rows) | set(after_rows)):
            before = before_rows.get(row_key)
            after = after_rows.get(row_key)
            base = f"rows.{section}[{row_key}]"
            if before is None:
                changes.append(Change("added", base, None, _row_text(after or {})))
            elif after is None:
                changes.append(Change("removed", base, _row_text(before), None))
            else:
                for cell in sorted(set(before) | set(after)):
                    old_value, new_value = before.get(cell), after.get(cell)
                    if old_value != new_value:
                        kind = (
                            "added"
                            if old_value is None
                            else "removed"
                            if new_value is None
                            else "changed"
                        )
                        changes.append(Change(kind, f"{base}.{cell}", old_value, new_value))
    return changes


def diff_markdown(changes: list[Change]) -> str:
    """Render changes as a compact Markdown table."""
    if not changes:
        return "No changes since the baseline."
    lines = ["| Change | Field / row | Old | New |", "|---|---|---|---|"]
    for change in changes:
        values = [change.kind, change.where, change.old or "", change.new or ""]
        cells = (value.replace("|", "\\|").replace("\n", " ") for value in values)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
