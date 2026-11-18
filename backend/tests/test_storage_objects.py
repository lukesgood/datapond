"""Storage browsing: folders, admin-only raw file access, and no deletes inside a table."""
import asyncio
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.api import storage as st
from app.api.auth import require_admin

T = datetime(2026, 11, 18, tzinfo=timezone.utc)


class FakeS3:
    def __init__(self, keys):
        self.keys = dict.fromkeys(keys, 10)
        self.deleted = []

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, MaxKeys=1000):
        hits = sorted(k for k in self.keys if k.startswith(Prefix))
        contents, prefixes = [], []
        for k in hits:
            rest = k[len(Prefix):]
            if Delimiter and Delimiter in rest:
                p = Prefix + rest.split(Delimiter, 1)[0] + Delimiter
                if p not in prefixes:
                    prefixes.append(p)
            else:
                contents.append({"Key": k, "Size": self.keys[k], "LastModified": T})
        out = {"Contents": contents[:MaxKeys], "IsTruncated": len(contents) > MaxKeys}
        if Delimiter:
            out["CommonPrefixes"] = [{"Prefix": p} for p in prefixes]
        return out

    def head_object(self, Bucket, Key):
        if Key not in self.keys:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        self.keys.pop(Key)


KEYS = ["warehouse/default.db/orders/metadata/00001-a.metadata.json",
        "warehouse/default.db/orders/data/part-0.parquet",
        "warehouse/default.db/export.csv",
        "README.md"]


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3(KEYS)
    monkeypatch.setattr(st, "get_s3_client", lambda: fake)
    return fake


def test_browse_lists_one_folder_level(s3):
    r = asyncio.run(st.browse_bucket("b", "warehouse/default.db"))
    assert r.prefix == "warehouse/default.db/"
    assert [f.name for f in r.folders] == ["orders"]
    assert [o.key for o in r.objects] == ["warehouse/default.db/export.csv"]
    root = asyncio.run(st.browse_bucket("b", ""))
    assert [f.name for f in root.folders] == ["warehouse"] and [o.key for o in root.objects] == ["README.md"]


def test_delete_outside_a_table_removes_the_object(s3):
    st._overview_cache["data"], st._overview_cache["ts"] = {"stale": True}, 1e12
    asyncio.run(st.delete_object("b", "warehouse/default.db/export.csv"))
    assert s3.deleted == ["warehouse/default.db/export.csv"]
    assert st._overview_cache["data"] is None


@pytest.mark.parametrize("key", ["warehouse/default.db/orders/data/part-0.parquet",
                                 "warehouse/default.db/orders/metadata/00001-a.metadata.json"])
def test_delete_inside_an_iceberg_table_is_refused(s3, key):
    with pytest.raises(HTTPException) as e:
        asyncio.run(st.delete_object("b", key))
    assert e.value.status_code == 409 and "warehouse/default.db/orders/" in e.value.detail
    assert s3.deleted == []


def test_delete_of_a_missing_object_is_404(s3):
    with pytest.raises(HTTPException) as e:
        asyncio.run(st.delete_object("b", "nope.txt"))
    assert e.value.status_code == 404


def _deps(path, method):
    for r in st.router.routes:
        if r.path == path and method in r.methods:
            return [d.call for d in r.dependant.dependencies]
    raise AssertionError(f"no route {method} {path}")


@pytest.mark.parametrize("path,method", [
    ("/storage/buckets/{bucket_name}/browse", "GET"),
    ("/storage/buckets/{bucket_name}/objects", "GET"),
    ("/storage/objects/{bucket}/{key:path}", "GET"),
    ("/storage/objects/{bucket}/{key:path}", "DELETE"),
    ("/storage/objects/{bucket}/{key:path}", "PUT"),
])
def test_raw_object_access_is_admin_only(path, method):
    assert require_admin in _deps(path, method)


def test_overview_counts_stay_open_to_every_signed_in_user():
    assert require_admin not in _deps("/storage/overview", "GET")
