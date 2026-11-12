"""Keeping a mirror's registration on its owner's current snapshot (app/mirror_freshness.py).

fresh    — the mirror's current metadata file is the owner's: nothing to do.
stale    — the owner committed since; the mirror still points where we registered it:
           re-point it (unregister + register at the owner's file; no data copied).
diverged — the mirror's current file is neither ours nor the owner's: someone committed
           through the mirror from outside DataPond. Not overwritten; reported."""
import pytest

from app import mirror_freshness as mf

OWNER_META = "s3://lake/warehouse/default.db/orders-1/metadata/00005-b.metadata.json"
OLD_META = "s3://lake/warehouse/default.db/orders-1/metadata/00003-a.metadata.json"
LINK = {"mirror_catalog": "polaris_lake", "mirror_schema": "default", "mirror_table": "orders",
        "owner_catalog": "iceberg", "owner_schema": "default", "owner_table": "orders",
        "location": "s3://lake/warehouse/default.db/orders-1", "mirror_metadata_file": "00003-a.metadata.json"}


class Cursor:
    def __init__(self, files, fail=None):
        self.files, self.fail, self.executed, self._rows = dict(files), fail, [], []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.executed.append(s)
        if "$metadata_log_entries" in s:
            cat = s.split(" FROM ")[1].split(".")[0].strip('"')
            self._rows = [(self.files[cat],)]
        elif s.startswith("CALL"):
            if self.fail:
                raise RuntimeError(self.fail)
            if "register_table(" in s and "unregister" not in s:
                self.files["polaris_lake"] = OWNER_META
            self._rows = []
        else:
            raise AssertionError(s)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def test_a_mirror_on_the_owner_s_file_is_fresh():
    cur = Cursor({"iceberg": OWNER_META, "polaris_lake": OWNER_META})
    r = mf.check_one(cur, LINK)
    assert r.status == "fresh" and not any(s.startswith("CALL") for s in cur.executed)


def test_a_mirror_behind_its_owner_is_repointed_without_copying():
    cur = Cursor({"iceberg": OWNER_META, "polaris_lake": OLD_META})
    r = mf.check_one(cur, LINK)
    assert r.status == "fresh" and r.refreshed and r.metadata_file == "00005-b.metadata.json"
    calls = [s for s in cur.executed if s.startswith("CALL")]
    assert calls == [
        "CALL \"polaris_lake\".system.unregister_table(schema_name => 'default', table_name => 'orders')",
        "CALL \"polaris_lake\".system.register_table(schema_name => 'default', table_name => 'orders', "
        "table_location => 's3://lake/warehouse/default.db/orders-1', metadata_file_name => '00005-b.metadata.json')"]


def test_a_commit_through_the_mirror_is_reported_not_overwritten():
    other = "s3://lake/warehouse/default.db/orders-1/metadata/00004-x.metadata.json"
    cur = Cursor({"iceberg": OWNER_META, "polaris_lake": other})
    r = mf.check_one(cur, LINK)
    assert r.status == "diverged" and "00004-x.metadata.json" in r.detail
    assert not any(s.startswith("CALL") for s in cur.executed)


def test_a_failed_repoint_is_an_error_with_the_engine_message():
    cur = Cursor({"iceberg": OWNER_META, "polaris_lake": OLD_META}, fail="Access Denied")
    r = mf.check_one(cur, LINK)
    assert r.status == "error" and "Access Denied" in r.detail


def test_a_moved_owner_location_is_followed():
    moved = "s3://lake/warehouse/default.db/orders-2/metadata/00001-c.metadata.json"
    cur = Cursor({"iceberg": moved, "polaris_lake": OLD_META})
    r = mf.check_one(cur, LINK)
    assert r.status == "fresh" and r.location == "s3://lake/warehouse/default.db/orders-2"
    assert "table_location => 's3://lake/warehouse/default.db/orders-2'" in cur.executed[-1]
