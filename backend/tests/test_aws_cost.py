from datetime import datetime, timedelta, timezone

import pytest

from app import aws_cost, aws_infra

UTC = timezone.utc
NOW = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)   # 12:00 KST, a Friday
SCHED = {"days": ["MON", "TUE", "WED", "THU", "FRI"], "start": "07:30", "stop": "18:00",
         "tz": "Asia/Seoul", "enabled": True}


def test_cron_round_trip():
    assert aws_cost.parse_cron("cron(30 7 ? * MON-FRI *)") == {"days": SCHED["days"], "time": "07:30"}
    assert aws_cost.build_cron(SCHED["days"], "07:30") == "cron(30 7 ? * MON-FRI *)"
    assert aws_cost.build_cron(["SAT", "MON"], "9:05") == "cron(5 9 ? * MON,SAT *)"
    assert aws_cost.parse_cron("cron(0/5 * * * ? *)") is None
    with pytest.raises(ValueError):
        aws_cost.build_cron([], "07:00")
    with pytest.raises(ValueError):
        aws_cost.build_cron(["MON"], "25:00")


def test_weekly_hours():
    assert aws_cost.weekly_hours(SCHED) == 52.5
    assert aws_cost.weekly_hours(dict(SCHED, enabled=False)) == 168
    assert aws_cost.weekly_hours(None) == 168


def test_scheduled_hours_follow_the_timezone():
    # Saturday 00:00 UTC → Sunday 00:00 UTC: Saturday in Seoul, nothing scheduled.
    sat = datetime(2026, 11, 21, 0, 0, tzinfo=UTC)
    assert aws_cost.scheduled_hours_between(SCHED, sat, sat + timedelta(days=1)) == 0
    # Monday KST 07:30–18:00 rounds to the hours 08..17 → 10 hourly steps (07:00 is before 07:30)
    mon = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)   # Mon 00:00 KST
    assert aws_cost.scheduled_hours_between(SCHED, mon, mon + timedelta(days=1)) == 10


def _usage():
    start, _ = aws_cost.month_bounds(NOW)
    hours = [start + timedelta(hours=h) for h in range(int((NOW - start).total_seconds() // 3600))]
    return {
        "aurora": {"acu_hourly": [(t, 0.5) for t in hours], "storage_gb": 3.1, "min_acu": 0.5},
        "node": {"running_hours": hours[::3], "hourly_price": 0.05, "lifecycle": "spot",
                 "instance_type": "t3.xlarge", "volume_gb": 100},
        "schedule": SCHED, "public_ips": 1, "hosted_zones": 1, "alarms": 2, "dashboards": 1,
        "custom_metrics": 4, "secrets": 3, "s3_gb": 0.0946,
        "ai_spend": [(start + timedelta(days=2), 1.2), (start - timedelta(days=1), 99.0)],
    }


def test_estimate_month_to_date_and_forecast():
    est = aws_cost.estimate(_usage(), NOW)
    by = {s["key"]: s for s in est["services"]}
    hours = int((NOW - aws_cost.month_bounds(NOW)[0]).total_seconds() // 3600)
    # Aurora: 0.5 ACU every hour so far × $0.12, plus storage pro rata
    assert by["aurora"]["mtd"] == pytest.approx(hours * 0.5 * 0.12 + 3.1 * 0.10 * hours / 720, abs=0.01)
    assert by["aurora"]["forecast"] == pytest.approx(720 * 0.5 * 0.12 + 0.31, abs=0.05)
    # Bedrock: last month's call is not this month's
    assert by["bedrock"]["mtd"] == 1.2
    # EC2 forecast adds only scheduled hours ahead
    assert by["ec2"]["forecast"] > by["ec2"]["mtd"]
    assert est["total"]["mtd"] == pytest.approx(sum(s["mtd"] for s in est["services"]), abs=0.02)
    assert est["services"][0]["key"] == "aurora"          # largest forecast first
    assert len(est["daily"]) == 30
    assert est["daily"][0]["forecast"] is False and est["daily"][-1]["forecast"] is True
    # forecast weekends carry no EC2 cost under a weekday schedule
    assert next(d for d in est["daily"] if d["day"] == "2026-11-28")["ec2"] == 0


def test_savings():
    s = aws_cost.savings(_usage())
    assert s["aurora_idle_floor"] == pytest.approx(0.5 * 0.12 * 730, abs=0.01)
    assert s["spot_vs_on_demand"] == pytest.approx((0.1664 - 0.05) * 730 * 52.5 / 168, abs=0.01)
    assert s["schedule_saves"] == pytest.approx((1 - 52.5 / 168) * 730 * 0.05, abs=0.01)


def test_budget_state():
    assert aws_cost.budget_state(100.3, 150) == {"pct": 67, "over": False, "budget": 150}
    assert aws_cost.budget_state(160, 150)["over"] is True
    assert aws_cost.budget_state(100, None) is None


def test_resource_names(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "datapond-pg.cluster-abc.us-east-1.rds.amazonaws.com")
    monkeypatch.setenv("GLUE_WAREHOUSE", "s3://datapond-data-123/warehouse")
    monkeypatch.delenv("AWS_INFRA_DB_CLUSTER", raising=False)
    assert aws_infra.db_cluster_id() == "datapond-pg"
    assert aws_infra.bucket_name() == "datapond-data-123"
    assert aws_infra.schedule_names() == {"start": "datapond-node-start", "stop": "datapond-node-stop"}


class _Denied(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code, "Message": "no"}}


def test_refused_calls_are_named_not_fatal():
    calls = aws_infra._Calls()
    assert calls("rds:DescribeDBClusters", lambda: (_ for _ in ()).throw(_Denied("AccessDenied")), {}) == {}
    assert calls("x:Y", lambda: (_ for _ in ()).throw(_Denied("Throttling")), None) is None
    assert calls.missing == ["rds:DescribeDBClusters"] and len(calls.errors) == 1


class _PayerDenied(Exception):
    response = {"Error": {"Code": "AccessDeniedException"}}

    def __str__(self):
        return ("An error occurred (AccessDeniedException) when calling the GetCostAndUsage operation: "
                "Payer account 111111111111 does not allow access for linked account 222222222222")


def test_payer_block_is_not_reported_as_missing_iam(monkeypatch):
    class _Ce:
        def get_cost_and_usage(self, **_):
            raise _PayerDenied()
    monkeypatch.setattr(aws_infra, "_client", lambda *_: _Ce())
    aws_infra._cache.pop("ce", None)
    out = aws_infra.actual_costs()
    aws_infra._cache.pop("ce", None)
    assert out == {"active": False, "missing": [], "blocked": "payer"}


def test_schedule_view_editable_only_when_both_parse():
    names = aws_infra.schedule_names()
    s = {"names": names,
         "start": {"expression": "cron(30 7 ? * MON-FRI *)", "state": "ENABLED", "tz": "Asia/Seoul",
                   "parsed": aws_cost.parse_cron("cron(30 7 ? * MON-FRI *)")},
         "stop": {"expression": "cron(0 18 ? * MON-FRI *)", "state": "ENABLED", "tz": "Asia/Seoul",
                  "parsed": aws_cost.parse_cron("cron(0 18 ? * MON-FRI *)")}}
    v = aws_infra._schedule_view(s)
    assert v["editable"] and v["start"] == "07:30" and v["stop"] == "18:00" and v["enabled"]
    s["stop"]["parsed"] = None
    assert aws_infra._schedule_view(s)["editable"] is False
    assert aws_infra._schedule_view({"names": names})["known"] is False


def test_set_aurora_capacity_rejects_odd_ranges():
    with pytest.raises(ValueError):
        aws_infra.set_aurora_capacity(2, 2)
    with pytest.raises(ValueError):
        aws_infra.set_aurora_capacity(0.25, 4)


def test_routes_absent_when_off(monkeypatch):
    from fastapi import HTTPException

    from app.api import infra_aws
    monkeypatch.delenv("AWS_INFRA_ENABLED", raising=False)
    with pytest.raises(HTTPException) as e:
        infra_aws._on()
    assert e.value.status_code == 404


def test_expected_starts_spec():
    from app.api.infra_aws import _expected_starts
    assert _expected_starts(SCHED["days"], "07:30", "Asia/Seoul") == "MON-FRI 07:30 Asia/Seoul"


def test_gather_with_no_permissions_still_answers(monkeypatch):
    """Before the IAM is applied every call is refused: the page must still render."""
    class Refuse:
        def __getattr__(self, name):
            def f(*a, **k):
                raise _Denied("AccessDenied")
            return f
    monkeypatch.setattr(aws_infra, "_client", lambda name, region: Refuse())
    monkeypatch.setattr(aws_infra, "cloud_info", lambda: {"instance_id": "i-1", "region": "us-east-1",
                                                          "instance_type": "t3.xlarge", "lifecycle": "spot",
                                                          "availability_zone": "us-east-1a"})
    out = aws_infra.gather(NOW)
    assert "rds:DescribeDBClusters" in out["missing"] and "cloudwatch:GetMetricData" in out["missing"]
    assert out["node"]["instance_type"] == "t3.xlarge"
    assert out["schedule"]["known"] is False
    est = aws_cost.estimate(dict(out["usage"], ai_spend=[]), NOW)
    assert est["total"]["mtd"] >= 0
