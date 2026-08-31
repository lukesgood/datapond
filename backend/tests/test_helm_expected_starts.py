"""The AWS reference profile declares the schedule its node actually runs on.

The node is stopped at 18:00 and started at 07:30 on weekdays by an EventBridge
schedule, to save money on a spot instance. Without the window declared, the collector
reports every Monday morning as `critical — cause not recorded`: two expected events a
week that teach whoever reads the list to ignore the severity, and the one unscheduled
restart is then indistinguishable from them.

Fail-closed elsewhere: a profile that does not know its node's schedule declares
nothing, and every restart stays critical.
"""
from pathlib import Path

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"


def test_the_backend_is_told_about_expected_starts():
    body = (CHART / "templates/backend-deployment.yaml").read_text()
    assert "SYSTEM_EVENTS_EXPECTED_STARTS" in body


def test_the_aws_reference_declares_the_window_its_scheduler_uses():
    values = (CHART / "values-prod-single.yaml").read_text()
    assert "MON-FRI 07:30 Asia/Seoul" in values, (
        "EventBridge datapond-node-start is cron(30 7 ? * MON-FRI *) Asia/Seoul")


def test_other_profiles_declare_nothing_and_stay_loud():
    values = (CHART / "values.yaml").read_text()
    assert 'expectedStarts: ""' in values


def test_the_declared_window_parses():
    """A typo here is silent: an unparseable window is dropped, and the deployment
    goes back to calling every scheduled start critical."""
    import re

    from app.system_events import parse_expected_starts

    values = (CHART / "values-prod-single.yaml").read_text()
    declared = re.search(r'expectedStarts:\s*"([^"]*)"', values).group(1)
    assert parse_expected_starts(declared), f"does not parse: {declared!r}"
