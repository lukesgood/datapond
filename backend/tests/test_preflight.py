"""Install/deploy pre-check (design thinking A3): the failures we hit live — Spot capacity
missing at the 07:30 start, CPU requests at 95% blocking a rolling update — reported
before an install or a deploy instead of after."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("preflight", Path(__file__).resolve().parents[2] / "scripts/preflight.py")
pf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pf)


def test_spot_placement_score_in_the_chosen_zone():
    scores = [{"AvailabilityZoneId": "use1-az1", "Score": 1}, {"AvailabilityZoneId": "use1-az6", "Score": 3}]
    r = pf.check_spot(scores, "use1-az1", "m6a.xlarge")
    assert r.level == "warn" and "use1-az6" in r.detail
    assert pf.check_spot([{"AvailabilityZoneId": "use1-az1", "Score": 3}], "use1-az1", "t3.xlarge").level == "ok"
    assert pf.check_spot([], "use1-az1", "t3.xlarge").level == "warn"


def test_spot_vcpu_quota():
    assert pf.check_quota(32.0, 4).level == "ok"
    assert pf.check_quota(2.0, 4).level == "fail"


def test_cpu_request_headroom_for_a_rolling_update():
    # 4 vCPU node, 3.8 requested: a new backend pod (500m) cannot schedule beside the old one
    r = pf.check_headroom(allocatable_m=4000, requested_m=3800, largest_rolling_m=500)
    assert r.level == "fail" and "500m" in r.detail and "200m" in r.detail
    assert pf.check_headroom(4000, 3000, 500).level == "ok"


def test_parsing_kubernetes_cpu_quantities():
    assert pf.cpu_m("500m") == 500 and pf.cpu_m("2") == 2000 and pf.cpu_m("1.5") == 1500 and pf.cpu_m(None) == 0


def test_the_report_fails_when_any_check_fails():
    ok, warn, fail = pf.Check("a", "ok", ""), pf.Check("b", "warn", ""), pf.Check("c", "fail", "")
    assert pf.exit_code([ok, warn]) == 0 and pf.exit_code([ok, fail]) == 1
