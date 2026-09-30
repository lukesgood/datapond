"""Glue cross-account catalogs: registry `role_arn` -> STS AssumeRole, cached and refreshed
before expiry, credentials handed to pyiceberg and never logged or returned. STS and boto3
are mocked; nothing touches the network."""
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from app import aws_assume_role as ar
from app import catalog_registry as reg
from app.api import catalog_backend as cb
from app.catalog_registry import CatalogEntry

ROLE = "arn:aws:iam::210987654321:role/datapond-catalog-read"


def _entry(**cfg):
    base = {"region": "us-east-1", "catalog_id": "210987654321", "role_arn": ROLE}
    base.update(cfg)
    return CatalogEntry(name="partner", kind="glue", engine_catalog="partner",
                        config=base, is_default=False, enabled=True)


class _Sts:
    def __init__(self, ttl=3600, fail=None):
        self.calls, self.ttl, self.fail = [], ttl, fail

    def assume_role(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail
        n = len(self.calls)
        return {"Credentials": {
            "AccessKeyId": f"ASIA{n}", "SecretAccessKey": f"secret-{n}-zzzz",
            "SessionToken": f"token-{n}-zzzz",
            "Expiration": datetime.now(timezone.utc) + timedelta(seconds=self.ttl)}}


@pytest.fixture
def sts(monkeypatch):
    ar.forget()
    client = _Sts()
    fake = types.SimpleNamespace(client=lambda svc, **kw: client)
    monkeypatch.setitem(sys.modules, "boto3", fake)
    yield client
    ar.forget()


def test_role_arn_validation():
    for good in (ROLE, "arn:aws-us-gov:iam::123456789012:role/path/to/r+=,.@-_"):
        ar.validate_role(good)
    for bad in ("", "arn:aws:iam::123:role/x", "arn:aws:iam::123456789012:user/x",
                "arn:aws:s3:::bucket", "arn:aws:iam::123456789012:role/", ROLE + " "):
        with pytest.raises(ValueError):
            ar.validate_role(bad)
    with pytest.raises(ValueError):
        ar.validate_role(ROLE, "x")   # external id too short


def test_registry_config_validation():
    ok = reg.validate_config("glue", {"region": "us-east-1", "role_arn": ROLE,
                                      "external_id": "ext-123"})
    assert ok["role_arn"] == ROLE
    with pytest.raises(ValueError):
        reg.validate_config("glue", {"role_arn": "nope"})
    with pytest.raises(ValueError):
        reg.validate_config("glue", {"external_id": "ext-123"})
    with pytest.raises(ValueError):
        reg.validate_config("polaris", {"role_arn": ROLE})


def test_session_parameters_and_cache(sts):
    c1 = ar.assumed_credentials("partner", ROLE, "ext-123", "us-east-1")
    c2 = ar.assumed_credentials("partner", ROLE, "ext-123", "us-east-1")
    assert c1 == c2 and len(sts.calls) == 1
    call = sts.calls[0]
    assert call["RoleArn"] == ROLE and call["ExternalId"] == "ext-123"
    assert call["RoleSessionName"] == "datapond-catalog-partner"
    assert call["DurationSeconds"] == 3600
    ar.assumed_credentials("other", ROLE)          # another entry: another session
    assert len(sts.calls) == 2 and "ExternalId" not in sts.calls[1]


def test_refresh_before_expiry(sts, monkeypatch):
    first = ar.assumed_credentials("partner", ROLE)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(ar, "_now", lambda: now + timedelta(seconds=3600 - 400))
    assert ar.assumed_credentials("partner", ROLE) == first and len(sts.calls) == 1
    monkeypatch.setattr(ar, "_now", lambda: now + timedelta(seconds=3600 - 200))
    second = ar.assumed_credentials("partner", ROLE)
    assert len(sts.calls) == 2 and second != first


def test_credentials_reach_pyiceberg_props(sts):
    g = ar.glue_credential_props(_entry())
    assert g["glue.access-key-id"] == "ASIA1" and g["glue.session-token"] == "token-1-zzzz"
    assert g["s3.secret-access-key"] == "secret-1-zzzz"
    r = cb.rest_properties(_entry(via_rest=True), None)
    assert r["client.access-key-id"] == "ASIA1" and r["client.session-token"] == "token-1-zzzz"
    assert r["s3.access-key-id"] == "ASIA1" and r["rest.signing-name"] == "glue"
    assert len(sts.calls) == 1                      # shared through the cache


def test_no_role_no_credentials(sts):
    e = _entry()
    e.config.pop("role_arn")
    assert ar.glue_credential_props(e) == {} and ar.rest_credential_props(e) == {}
    assert sts.calls == []


def test_errors_are_sanitised_and_not_retried_at_once(sts):
    class Boom(Exception):
        response = {"Error": {"Code": "AccessDenied"}}
    sts.fail = Boom("User arn:aws:sts::1:assumed-role/x is not authorized; AKIASECRETKEY123")
    with pytest.raises(ar.AssumeRoleError) as ei:
        ar.assumed_credentials("partner", ROLE)
    assert "AccessDenied" in str(ei.value) and "AKIASECRETKEY123" not in str(ei.value)
    with pytest.raises(ar.AssumeRoleError):
        ar.assumed_credentials("partner", ROLE)
    assert len(sts.calls) == 1                      # the refusal is remembered briefly


def test_rest_catalog_unavailable_on_sts_failure(sts):
    cb.reset_rest_cache()
    sts.fail = RuntimeError("no")
    with pytest.raises(cb.CatalogUnavailable) as ei:
        cb.get_rest_catalog(_entry(via_rest=True))
    assert "partner" in str(ei.value)


def test_glue_catalog_built_with_assumed_credentials(sts, monkeypatch):
    from app.connectors import iceberg_catalog as ic
    seen = []

    class FakeGlue:
        def __init__(self, name, **props):
            seen.append(props)
    monkeypatch.setitem(sys.modules, "pyiceberg.catalog.glue",
                        types.SimpleNamespace(GlueCatalog=FakeGlue))
    ic._by_entry.clear()
    ic.get_catalog_for(_entry())
    ic.get_catalog_for(_entry())
    assert len(seen) == 1
    assert seen[0]["glue.session-token"] == "token-1-zzzz" and seen[0]["glue.id"] == "210987654321"
    ic._by_entry.clear()
