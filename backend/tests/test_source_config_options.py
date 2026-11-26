"""Source options. S3: the folder prefix is joined with a slash, a table is a folder (not a name
prefix), and the setup step lists columns for Parquet and JSON folders as well as CSV. REST: the credential is masked when the config is read."""
import asyncio
import io

import pandas as pd

from app.connectors.base import ConnectorType
from app.connectors.storage import S3Connector, StorageConfig


class _S3:
    def __init__(self, objects):
        self.objects = objects

    def get_paginator(self, _):
        objects = self.objects

        class _P:
            def paginate(self, Bucket, Prefix, PaginationConfig=None):
                return [{"Contents": [{"Key": k, "Size": len(v), "ETag": '"e"',
                                       "LastModified": pd.Timestamp("2026-11-26")}
                                      for k, v in objects.items() if k.startswith(Prefix)]}]
        return _P()

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


def _parquet(df):
    b = io.BytesIO(); df.to_parquet(b); return b.getvalue()


def _conn(prefix, objects):
    c = S3Connector(StorageConfig(name="s", connector_type=ConnectorType.S3, bucket="b", prefix=prefix))
    c._s3_client = _S3(objects)
    return c


def test_prefix_means_a_folder_however_it_is_typed():
    for typed in ("data", "/data", "data/", " data// "):
        assert StorageConfig(name="s", connector_type=ConnectorType.S3, bucket="b", prefix=typed).prefix == "data/"
    assert StorageConfig(name="s", connector_type=ConnectorType.S3, bucket="b", prefix="").prefix == ""


def test_a_table_folder_does_not_take_in_a_folder_that_shares_its_name():
    c = _conn("data", {"data/orders/a.csv": b"id\n1\n", "data/orders_old/b.csv": b"id\n2\n"})
    files = asyncio.run(c.list_files(prefix="orders"))
    assert [f["key"] for f in files] == ["data/orders/a.csv"]


def test_columns_are_listed_for_a_parquet_folder():
    c = _conn("", {"events/part-0.parquet": _parquet(pd.DataFrame({"id": [1], "at": ["x"]})),
                   "events/_SUCCESS": b""})
    schema = asyncio.run(c.get_schema("events"))
    assert [col.name for col in schema.columns] == ["id", "at"]


def test_preview_reads_json_lines_too():
    c = _conn("", {"scans/a.jsonl": b'{"id": 1}\n{"id": 2}\n'})
    assert asyncio.run(c.read_data("scans")) == [{"id": 1}, {"id": 2}]


def test_a_rest_credential_is_masked_when_the_config_is_read():
    from app.api.connectors import _is_secret_field
    assert all(_is_secret_field(k) for k in ("password", "secret_key", "access_key", "credentials_key", "auth_value", "api_token"))
    assert not any(_is_secret_field(k) for k in ("host", "base_url", "auth_type", "auth_header", "data_path", "bucket", "code"))
