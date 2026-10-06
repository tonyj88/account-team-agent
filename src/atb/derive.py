"""Pure date and number derivations used by account plans."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Literal


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_review(last_reviewed: date, arr_usd: float | None, policy: dict) -> date:
    """Return the next review date using the configured ARR cadence."""
    threshold = policy["high_value_arr_threshold_usd"]
    cadence = (
        policy["high_value_cadence"]
        if arr_usd is not None and arr_usd >= threshold
        else policy["default_cadence"]
    )
    months = {"quarterly": 3, "semiannual": 6}[cadence]
    return _add_months(last_reviewed, months)


def parse_usd(text: str) -> float | None:
    """Parse a dollar amount, optionally abbreviated with k or m."""
    value = text.strip().replace(",", "")
    value = re.sub(r"^USD\s*", "", value, flags=re.IGNORECASE).replace("$", "").strip()
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([kKmM]?)", value)
    if not match:
        return None
    amount = float(match.group(1))
    suffix = match.group(2).casefold()
    return amount * (1_000 if suffix == "k" else 1_000_000 if suffix == "m" else 1)


def growth_gap(target_usd: float | None, current_usd: float | None) -> float | None:
    """Return target minus current, if both amounts are known."""
    return None if target_usd is None or current_usd is None else target_usd - current_usd


def action_bucket(due: date, plan_date: date) -> Literal["d30", "d60", "d90", "later", "overdue"]:
    """Bucket an action by its due date relative to the plan date."""
    days = (due - plan_date).days
    if days < 0:
        return "overdue"
    if days <= 30:
        return "d30"
    if days <= 60:
        return "d60"
    if days <= 90:
        return "d90"
    return "later"


def renewal_in_final_two_quarters(renewal: date, plan_date: date) -> bool:
    """Whether renewal falls within the next 182 days, including either endpoint."""
    return plan_date <= renewal <= plan_date + timedelta(days=182)


def parse_date(text: str) -> date | None:
    """Parse common ISO, written month, or US numeric dates."""
    value = text.strip()
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return (
                date.fromisoformat(value)
                if fmt == "%Y-%m-%d"
                else datetime.strptime(value, fmt).date()
            )
        except ValueError:
            pass
    return None
