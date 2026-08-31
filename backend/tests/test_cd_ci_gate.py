"""The gate that stops CD from shipping a commit whose tests failed.

`require-ci` asks the API what happened to this exact commit and refuses to let
`build-and-push` run otherwise. It is the only thing standing between a red test run
and an image in GHCR tagged with that SHA, so the ways it can fail *open* — or fail
closed on every commit, which is the same outage in the other direction — are worth
pinning here rather than discovering on a release.
"""
from pathlib import Path

import yaml

CD_PATH = Path(__file__).resolve().parents[2] / ".github/workflows/cd.yml"
CD = yaml.safe_load(CD_PATH.read_text())
CD_TEXT = CD_PATH.read_text()

# PyYAML reads the bare `on:` key as the boolean True.
TRIGGERS = CD.get("on") or CD.get(True)


def test_the_gate_may_read_the_endpoint_it_queries():
    """The step calls `gh api repos/.../actions/runs`, which needs `actions: read`.

    A job-level `permissions:` block is exhaustive: every scope it does not name is
    set to `none`, so listing `checks: read` alone makes that call 403. Under
    `set -euo pipefail` the failing command substitution ends the step immediately —
    it never reaches the retry loop — and since build-and-push needs this job, every
    push to main and every tag would fail to publish an image at all.
    """
    job = CD["jobs"]["require-ci"]
    script = " ".join(str(step.get("run", "")) for step in job["steps"])
    if "actions/runs" in script:
        assert job.get("permissions", {}).get("actions") == "read", (
            "require-ci queries the Actions API but does not grant itself actions: read")
    if "/check-runs" in script or "/commits/" in script:
        assert job.get("permissions", {}).get("checks") == "read"


def test_nothing_is_built_or_pushed_before_the_gate_passes():
    for name, job in CD["jobs"].items():
        if name == "require-ci":
            continue
        needs = job.get("needs")
        needs = [needs] if isinstance(needs, str) else (needs or [])
        assert needs, f"job '{name}' runs without waiting for the CI gate"


def test_the_gate_fails_closed_when_it_cannot_tell():
    """A timeout, a missing run, or any conclusion other than success must all end in
    a non-zero exit. The failure mode this guards is a script that falls off the end
    of its retry loop and returns 0 by default, which would publish exactly the
    commits nobody could verify."""
    script = " ".join(str(step.get("run", "")) for step in CD["jobs"]["require-ci"]["steps"])
    assert "set -euo pipefail" in script
    assert script.rstrip().endswith("exit 1"), (
        "the retry loop's last word must be a refusal, not an implicit success")
