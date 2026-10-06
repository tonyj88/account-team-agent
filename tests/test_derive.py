from datetime import date, timedelta

import pytest

from atb.derive import (
    action_bucket,
    growth_gap,
    next_review,
    parse_date,
    parse_usd,
    renewal_in_final_two_quarters,
)


@pytest.mark.parametrize(
    "last, cadence, expected",
    [
        (date(2026, 11, 30), "quarterly", date(2027, 2, 28)),
        (date(2024, 11, 30), "quarterly", date(2025, 2, 28)),
        (date(2026, 8, 31), "semiannual", date(2027, 2, 28)),
    ],
)
def test_next_review(last, cadence, expected):
    policy = {
        "high_value_arr_threshold_usd": 1000,
        "high_value_cadence": cadence,
        "default_cadence": "quarterly",
    }
    assert next_review(last, 2000, policy) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("$1,234,567", 1234567),
        ("1.2M", 1200000),
        ("450k", 450000),
        ("USD 300,000.00", 300000),
        ("not money", None),
    ],
)
def test_parse_usd(text, expected):
    assert parse_usd(text) == expected


def test_growth_bucket_and_renewal():
    assert growth_gap(10, 4) == 6
    base = date(2026, 1, 1)
    assert action_bucket(date(2026, 1, 31), base) == "d30"
    assert action_bucket(date(2026, 3, 2), base) == "d60"
    assert action_bucket(date(2026, 4, 1), base) == "d90"
    assert action_bucket(date(2026, 4, 2), base) == "later"
    assert action_bucket(date(2025, 12, 31), base) == "overdue"
    assert renewal_in_final_two_quarters(base + timedelta(days=182), base)
    assert not renewal_in_final_two_quarters(base + timedelta(days=183), base)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-09-30", date(2026, 9, 30)),
        ("30 Sep 2026", date(2026, 9, 30)),
        ("Sep 30, 2026", date(2026, 9, 30)),
        ("9/30/2026", date(2026, 9, 30)),
        ("bad", None),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == expected
