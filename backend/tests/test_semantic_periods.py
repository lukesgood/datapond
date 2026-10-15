from datetime import date

import pytest

from app.semantic.model import MetricInputError
from app.semantic.periods import resolve_period

TODAY = date(2026, 10, 15)


@pytest.mark.parametrize("period,start,end", [
    ("this_month", date(2026, 10, 1), date(2026, 11, 1)),
    ("last_month", date(2026, 9, 1), date(2026, 10, 1)),
    ("this_quarter", date(2026, 10, 1), date(2027, 1, 1)),
    ("last_quarter", date(2026, 7, 1), date(2026, 10, 1)),
    ("this_year", date(2026, 1, 1), date(2027, 1, 1)),
    ("last_year", date(2025, 1, 1), date(2026, 1, 1)),
    ("last_n_days:7", date(2026, 10, 9), date(2026, 10, 16)),
    ("2026-01-01..2026-03-31", date(2026, 1, 1), date(2026, 4, 1)),
])
def test_named_and_explicit_periods(period, start, end):
    assert resolve_period(period, TODAY) == (start, end)


def test_last_month_is_half_open():
    start, end = resolve_period("last_month", TODAY)
    assert end == date(2026, 10, 1)       # compared with <, so Oct 1 00:00 is excluded


def test_january_last_month_crosses_the_year():
    assert resolve_period("last_month", date(2026, 1, 20)) == (date(2025, 12, 1), date(2026, 1, 1))


@pytest.mark.parametrize("period", ["yesterday", "last_n_days:0", "2026-03-31..2026-01-01",
                                    "2026-13-01..2026-12-01", "", "last_n_days:x"])
def test_bad_periods(period):
    with pytest.raises(MetricInputError):
        resolve_period(period, TODAY)


def test_unknown_period_lists_the_allowed_forms():
    with pytest.raises(MetricInputError) as e:
        resolve_period("yesterday", TODAY)
    assert "last_month" in e.value.allowed["period"]
