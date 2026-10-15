"""`period` as a half-open date range [start, end). No I/O; `today` is passed in, so the
same request on the same day gives the same SQL."""
import re
from datetime import date, timedelta
from typing import Tuple

from app.semantic.model import MetricInputError

NAMED = ("this_month", "last_month", "this_quarter", "last_quarter", "this_year", "last_year")
_LAST_N = re.compile(r"^last_n_days:(\d{1,4})$")
_RANGE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")
FORMS = list(NAMED) + ["last_n_days:N", "YYYY-MM-DD..YYYY-MM-DD"]


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def resolve_period(period: str, today: date) -> Tuple[date, date]:
    p = str(period or "").strip()
    m = _RANGE.match(p)
    if m:
        try:
            start = date.fromisoformat(m.group(1))
            end = date.fromisoformat(m.group(2)) + timedelta(days=1)   # `to` is inclusive
        except ValueError:
            raise MetricInputError("period has an invalid date.", {"period": FORMS})
        if end <= start:
            raise MetricInputError("period ends before it starts.", {"period": FORMS})
        return start, end
    m = _LAST_N.match(p)
    if m:
        n = int(m.group(1))
        if n < 1:
            raise MetricInputError("last_n_days needs N >= 1.", {"period": FORMS})
        return today - timedelta(days=n - 1), today + timedelta(days=1)
    month0 = today.replace(day=1)
    quarter0 = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    ranges = {
        "this_month": (month0, _add_months(month0, 1)),
        "last_month": (_add_months(month0, -1), month0),
        "this_quarter": (quarter0, _add_months(quarter0, 3)),
        "last_quarter": (_add_months(quarter0, -3), quarter0),
        "this_year": (date(today.year, 1, 1), date(today.year + 1, 1, 1)),
        "last_year": (date(today.year - 1, 1, 1), date(today.year, 1, 1)),
    }
    if p in ranges:
        return ranges[p]
    raise MetricInputError(f"Unknown period {p!r}.", {"period": FORMS})
