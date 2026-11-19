"""What this deployment costs on AWS, estimated from what each resource used.

The Cost tab's first source (the second is Cost Explorer, once the Project cost tag
is active). Usage comes from CloudWatch and the EC2/RDS APIs (app/aws_infra.py);
this module turns it into dollars with AWS list prices for us-east-1 and the Spot
price the node actually paid. Pure: no I/O, so every number on the page has a test.

Deliberately not counted, and said so on the page: data transfer out, backups
beyond the free retention, ECR storage, KMS, the support plan, tax and credits.
An estimate that names what it leaves out is more useful than one that guesses.

Also here: the EventBridge Scheduler cron the node's start/stop schedules use
(`cron(30 7 ? * MON-FRI *)`), read and written for the "When the node runs" form.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# us-east-1 list prices, USD. Checked 2026-11; AWS changes these rarely and the
# page labels the figures "est.".
PRICES = {
    "aurora_acu_hour": 0.12,          # Aurora Serverless v2, Aurora Standard
    "aurora_storage_gb_month": 0.10,
    "gp3_gb_month": 0.08,
    "public_ipv4_hour": 0.005,
    "hosted_zone_month": 0.50,
    "cw_alarm_month": 0.10,
    "cw_dashboard_month": 3.00,       # first 3 dashboards free per account
    "cw_metric_month": 0.30,          # first 10 custom metrics free
    "secret_month": 0.40,
    "s3_gb_month": 0.023,
}

# On-demand Linux prices for the types a single node is likely to run on, to say
# what Spot saves. A type missing here just omits that sentence.
ON_DEMAND_HOURLY = {
    "t3.large": 0.0832, "t3.xlarge": 0.1664, "t3.2xlarge": 0.3328,
    "t3a.large": 0.0752, "t3a.xlarge": 0.1504, "t3a.2xlarge": 0.3008,
    "m6i.large": 0.096, "m6i.xlarge": 0.192, "m6i.2xlarge": 0.384,
    "m7i.large": 0.1008, "m7i.xlarge": 0.2016, "m7i.2xlarge": 0.4032,
    "r6i.large": 0.126, "r6i.xlarge": 0.252, "r6i.2xlarge": 0.504,
}

NOT_COUNTED = ["data transfer out", "backups beyond free retention", "ECR storage", "KMS",
               "support plan", "tax", "credits"]

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


# ── schedule ────────────────────────────────────────────────────────────────

_CRON = re.compile(r"^cron\((\d{1,2}) (\d{1,2}) \? \* ([A-Z,\-]+) \*\)$")


def _days(token: str) -> Optional[List[str]]:
    out: List[str] = []
    for part in token.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            if a not in DAYS or b not in DAYS or DAYS.index(a) > DAYS.index(b):
                return None
            out += DAYS[DAYS.index(a):DAYS.index(b) + 1]
        elif part in DAYS:
            out.append(part)
        else:
            return None
    return [d for d in DAYS if d in out]


def parse_cron(expr: str) -> Optional[Dict[str, Any]]:
    """`cron(30 7 ? * MON-FRI *)` → {"days": [...], "time": "07:30"}; None for any
    expression the form cannot build, so the page shows it as text instead of guessing."""
    m = _CRON.match((expr or "").strip())
    if not m:
        return None
    minute, hour = int(m.group(1)), int(m.group(2))
    days = _days(m.group(3))
    if days is None or not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return {"days": days, "time": f"{hour:02d}:{minute:02d}"}


def _day_token(days: Sequence[str]) -> str:
    idx = sorted(DAYS.index(d) for d in set(days))
    if len(idx) > 2 and idx == list(range(idx[0], idx[-1] + 1)):
        return f"{DAYS[idx[0]]}-{DAYS[idx[-1]]}"
    return ",".join(DAYS[i] for i in idx)


def build_cron(days: Sequence[str], time: str) -> str:
    """The inverse of parse_cron. Raises ValueError on a bad day or time."""
    bad = [d for d in days if d not in DAYS]
    if bad or not days:
        raise ValueError("Pick at least one day (MON…SUN).")
    hour, minute = parse_time(time)
    return f"cron({minute} {hour} ? * {_day_token(days)} *)"


def parse_time(time: str) -> Tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (time or "").strip())
    if not m or not (0 <= int(m.group(1)) < 24 and 0 <= int(m.group(2)) < 60):
        raise ValueError(f"Not a time: {time!r} (use HH:MM).")
    return int(m.group(1)), int(m.group(2))


def weekly_hours(schedule: Optional[Dict[str, Any]]) -> float:
    """Hours a week the node runs. No schedule, or one switched off, is 24/7."""
    if not schedule or not schedule.get("enabled", True):
        return 168.0
    try:
        sh, sm = parse_time(schedule["start"])
        eh, em = parse_time(schedule["stop"])
    except (KeyError, ValueError):
        return 168.0
    per_day = ((eh * 60 + em) - (sh * 60 + sm)) / 60
    if per_day <= 0:
        per_day += 24
    return round(per_day * len(schedule.get("days") or []), 2)


def _runs_at(schedule: Optional[Dict[str, Any]], at_local: datetime) -> bool:
    if not schedule or not schedule.get("enabled", True):
        return True
    sh, sm = parse_time(schedule["start"])
    eh, em = parse_time(schedule["stop"])
    minute = at_local.hour * 60 + at_local.minute
    return DAYS[at_local.weekday()] in (schedule.get("days") or []) and sh * 60 + sm <= minute < eh * 60 + em


def scheduled_hours_between(schedule: Optional[Dict[str, Any]], start: datetime, end: datetime) -> float:
    """Hours the schedule keeps the node running in [start, end), stepped hourly."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo((schedule or {}).get("tz") or "UTC")
    hours, t = 0, start.replace(minute=0, second=0, microsecond=0)
    while t < end:
        if _runs_at(schedule, t.astimezone(tz)):
            hours += 1
        t += timedelta(hours=1)
    return float(hours)


# ── estimate ────────────────────────────────────────────────────────────────

def month_bounds(now: datetime) -> Tuple[datetime, datetime]:
    start = now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days = calendar.monthrange(start.year, start.month)[1]
    return start, start + timedelta(days=days)


def _r(x: float) -> float:
    return round(float(x), 2)


def _by_day(points: Iterable[Tuple[datetime, float]]) -> Dict[date, float]:
    out: Dict[date, float] = {}
    for ts, v in points:
        d = ts.astimezone(timezone.utc).date()
        out[d] = out.get(d, 0.0) + float(v)
    return out


def estimate(usage: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Month-to-date and forecast per service, a cost-per-day series and the savings
    the page points at. See the module docstring for what `usage` holds."""
    start, end = month_bounds(now)
    elapsed_h = max((now - start).total_seconds() / 3600, 1.0)
    total_h = (end - start).total_seconds() / 3600
    remaining_h = total_h - elapsed_h
    month_frac = elapsed_h / total_h
    P = PRICES

    aurora = usage.get("aurora") or {}
    acu = [(ts, v) for ts, v in aurora.get("acu_hourly") or [] if ts >= start]
    acu_hours = sum(v for _, v in acu)
    recent = [v for ts, v in acu if ts >= now - timedelta(days=7)]
    acu_rate = (sum(recent) / len(recent)) if recent else (acu_hours / elapsed_h if acu else float(aurora.get("min_acu") or 0))
    storage_month = float(aurora.get("storage_gb") or 0) * P["aurora_storage_gb_month"]
    aurora_mtd = acu_hours * P["aurora_acu_hour"] + storage_month * month_frac
    aurora_fc = aurora_mtd + acu_rate * remaining_h * P["aurora_acu_hour"] + storage_month * (1 - month_frac)

    node = usage.get("node") or {}
    schedule = usage.get("schedule")
    running = sorted(ts for ts in node.get("running_hours") or [] if ts >= start)
    price = node.get("hourly_price")
    volume_month = float(node.get("volume_gb") or 0) * P["gp3_gb_month"]
    ec2_mtd = len(running) * (price or 0) + volume_month * month_frac
    ahead_h = scheduled_hours_between(schedule, now, end)
    ec2_fc = ec2_mtd + ahead_h * (price or 0) + volume_month * (1 - month_frac)

    ip_month = int(usage.get("public_ips") or 0) * P["public_ipv4_hour"] * total_h
    net_month = ip_month + int(usage.get("hosted_zones") or 0) * P["hosted_zone_month"]
    cw_month = (int(usage.get("alarms") or 0) * P["cw_alarm_month"]
                + max(int(usage.get("dashboards") or 0) - 3, 0) * P["cw_dashboard_month"]
                + max(int(usage.get("custom_metrics") or 0) - 10, 0) * P["cw_metric_month"])
    secrets_month = int(usage.get("secrets") or 0) * P["secret_month"]
    s3_month = float(usage.get("s3_gb") or 0) * P["s3_gb_month"]

    ai = [(ts, v) for ts, v in usage.get("ai_spend") or [] if ts >= start]
    ai_mtd = sum(v for _, v in ai)
    ai_fc = ai_mtd / month_frac if ai_mtd else 0.0

    def fixed(key, label, month, how):
        return {"key": key, "label": label, "mtd": _r(month * month_frac), "forecast": _r(month), "how": how}

    services = [
        {"key": "aurora", "label": "Aurora Serverless v2", "mtd": _r(aurora_mtd), "forecast": _r(aurora_fc),
         "how": f"ACU-hours from CloudWatch × ${P['aurora_acu_hour']} + storage"},
        {"key": "ec2", "label": "EC2 node + volume", "mtd": _r(ec2_mtd), "forecast": _r(ec2_fc),
         "how": ("hours running × " + ("Spot price history" if node.get("lifecycle") == "spot" else "on-demand price")
                 + f" + {int(node.get('volume_gb') or 0)} GB gp3")},
        fixed("network", "Public IP + Route 53", net_month, "fixed hourly + hosted zone"),
        fixed("cloudwatch", "CloudWatch", cw_month, "alarms, dashboards, custom metrics"),
        {"key": "bedrock", "label": "Bedrock", "mtd": _r(ai_mtd), "forecast": _r(ai_fc),
         "how": "AI Gateway spend log (per call)"},
        fixed("secrets", "Secrets Manager", secrets_month, "per secret per month"),
        fixed("s3", "S3", s3_month, f"bucket size × ${P['s3_gb_month']}/GB"),
    ]
    services.sort(key=lambda s: s["forecast"], reverse=True)
    mtd = sum(s["mtd"] for s in services)
    forecast = sum(s["forecast"] for s in services)

    # Cost per day: what was measured up to today, then the forecast at the schedule.
    acu_day = _by_day((ts, v * P["aurora_acu_hour"]) for ts, v in acu)
    ec2_day = _by_day((ts, price or 0) for ts in running)
    other_day = (net_month + cw_month + secrets_month + s3_month + volume_month + storage_month) / (total_h / 24)
    ai_day = _by_day(ai)
    daily = []
    d = start.date()
    while d < end.date():
        past = d < now.date()
        if past or d == now.date():
            a, e = acu_day.get(d, 0.0), ec2_day.get(d, 0.0)
        else:
            day_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            a = acu_rate * 24 * P["aurora_acu_hour"]
            e = scheduled_hours_between(schedule, day_start, day_start + timedelta(days=1)) * (price or 0)
        daily.append({"day": d.isoformat(), "aurora": _r(a), "ec2": _r(e),
                      "other": _r(other_day + (ai_day.get(d, 0.0) if past else ai_fc / (total_h / 24))),
                      "forecast": not past and d != now.date()})
        d += timedelta(days=1)

    return {
        "source": "estimate",
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days_elapsed": int(elapsed_h // 24) + 1},
        "services": services,
        "total": {"mtd": _r(mtd), "forecast": _r(forecast)},
        "daily": daily,
        "savings": savings(usage),
        "not_counted": NOT_COUNTED,
    }


def savings(usage: Dict[str, Any]) -> Dict[str, Any]:
    """Where the bill can go down, per month: Aurora's idle floor, Spot vs on-demand,
    and what the schedule already saves. None where the input is missing."""
    P = PRICES
    aurora = usage.get("aurora") or {}
    node = usage.get("node") or {}
    schedule = usage.get("schedule")
    month_h = 730
    min_acu = aurora.get("min_acu")
    floor = float(min_acu) * P["aurora_acu_hour"] * month_h if min_acu is not None else None
    hours_week = weekly_hours(schedule)
    run_frac = hours_week / 168
    price = node.get("hourly_price")
    od = ON_DEMAND_HOURLY.get(node.get("instance_type") or "")
    spot = (_r((od - price) * month_h * run_frac) if (od and price is not None and node.get("lifecycle") == "spot")
            else None)
    sched = _r((1 - run_frac) * month_h * price) if price is not None else None
    return {
        "aurora_idle_floor": _r(floor) if floor is not None else None,
        "aurora_min_acu": min_acu,
        "spot_vs_on_demand": spot,
        "on_demand_hourly": od,
        "schedule_saves": sched,
        "hours_per_week": hours_week,
    }


def budget_state(forecast: Optional[float], budget: Optional[float]) -> Optional[Dict[str, Any]]:
    """`{"pct": 67, "over": False}` of a monthly budget; None when either is unknown."""
    if forecast is None or not budget or budget <= 0:
        return None
    pct = round(forecast / budget * 100)
    return {"pct": pct, "over": forecast > budget, "budget": budget}
