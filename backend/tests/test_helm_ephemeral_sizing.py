"""The ephemeral profile has to fit on a two-CPU runner, with room to surge.

The upgrade deadlocked: two backends and two frontends were already running beside
Postgres, Valkey and the mock model, and a rolling update needs one more pod than it
has. `backend-d8f668dcf` sat Pending for twenty-four minutes while Helm waited for a
readiness that could not arrive, and `--atomic` then timed out rolling back too.

The profile exists to prove install, upgrade and rollback — not availability. One
replica of each proves all three and leaves room for the surge that an upgrade is.
"""
import re
from pathlib import Path

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"
EPHEMERAL = (CHART / "values-ephemeral.yaml").read_text()
CI = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()


def test_the_profile_runs_one_of_each():
    for component in ("backend", "frontend"):
        block = re.search(rf'^{component}:\n((?:[ \t].*\n|\n)*)', EPHEMERAL, re.M)
        assert block, f"{component} is not overridden at all — it inherits replicas: 2"
        assert re.search(r'^\s+replicas:\s*1\s*$', block.group(1), re.M), (
            f"{component} does not pin one replica")


def test_the_upgrade_step_does_not_add_a_pod():
    """The upgrade needs a visible difference for the rollback to undo. It must not be
    a replica count — that is the surge the node cannot fit."""
    step = CI.split("Upgrade, then roll back", 1)[1].split("- name:", 1)[0]
    assert "replicas=2" not in step, "the upgrade raises the replica count again"


def test_the_upgrade_still_changes_something_rollback_can_undo():
    step = CI.split("Upgrade, then roll back", 1)[1].split("- name:", 1)[0]
    overrides = re.findall(r'--set(?:-string)?\s+(\S+)=', step)
    changing = [o for o in overrides if "image." not in o]
    assert changing, "nothing distinguishes the second release from the first"
