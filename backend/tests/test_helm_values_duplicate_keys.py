"""No values file may declare the same top-level key twice.

YAML does not complain; the later block simply wins and the earlier one disappears.
That is how `postgres.persistence.storageClass: ""` vanished from the ephemeral
profile — a second `postgres:` block further down replaced it, postgres-0 stayed
Pending on a StorageClass kind does not have, and the failure surfaced three steps
away as a migration Job that could not reach a database.

The repository has been here before: 1edf384 fixed duplicate keys in values-prod.
"""
from collections import Counter
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"
PROFILES = sorted(CHART.glob("values*.yaml"))


def _top_level_keys(path: Path) -> list:
    keys = []
    for line in path.read_text().splitlines():
        if not line or line[0] in " #\t-":
            continue
        if ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    return keys


def test_there_are_profiles_to_check():
    assert len(PROFILES) >= 8


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.name)
def test_no_top_level_key_is_declared_twice(profile):
    repeated = [k for k, n in Counter(_top_level_keys(profile)).items() if n > 1]
    assert not repeated, f"{profile.name} declares {repeated} more than once"
