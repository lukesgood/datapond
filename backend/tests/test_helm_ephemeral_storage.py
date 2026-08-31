"""The ephemeral profile must not pin a storage class only k3s has.

`local-path` is the base default because the AWS reference node runs k3s, which ships
a StorageClass by that name. kind does not — its default is `standard` — so postgres-0
and valkey sat Pending for twelve minutes, the migration Job failed against a database
that never started, and the backend's init container waited for a schema nobody could
create. One unavailable StorageClass, three symptoms, none of them mentioning storage.

Empty means "use whatever this cluster's default is", which is the only portable
answer for a profile whose entire purpose is running on a cluster nobody configured.
"""
import re
from pathlib import Path

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"
EPHEMERAL = (CHART / "values-ephemeral.yaml").read_text()


def _declared(text: str) -> list:
    return re.findall(r'^\s*storageClass:\s*(.*?)\s*(?:#.*)?$', text, re.M)


def test_the_ephemeral_profile_pins_no_storage_class():
    values = _declared(EPHEMERAL)
    assert values, "the profile does not override storageClass at all"
    for value in values:
        assert value in ('""', "''"), f"pinned to {value}, which kind does not have"


def test_it_overrides_both_the_global_and_the_database_one():
    """postgres.persistence.storageClass does not inherit the global value — it has
    its own default of local-path, which is what actually left postgres-0 Pending."""
    assert "global:" in EPHEMERAL
    assert "persistence:" in EPHEMERAL


def test_the_base_profile_still_pins_local_path():
    """This is not a change to the AWS reference. k3s has local-path and the node's
    disk layout depends on it."""
    base = (CHART / "values.yaml").read_text()
    assert "storageClass: local-path" in base
