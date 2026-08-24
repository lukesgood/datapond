"""Medallion namespace bootstrap must not touch Trino on Trino-less profiles.

Live evidence (AWS single-node, FEATURE_TRINO=false): every backend boot logged
three `Failed to resolve 'trino.datapond.svc.cluster.local'` warnings because the
startup hook connected to Trino unconditionally.
"""
import logging
import sys
import types

import pytest


class _FakeCursor:
    def __init__(self, recorder):
        self._recorder = recorder

    def execute(self, sql):
        self._recorder.statements.append(sql)


class _FakeConn:
    def __init__(self, recorder):
        self._recorder = recorder

    def cursor(self):
        return _FakeCursor(self._recorder)


class _TrinoRecorder:
    """Stands in for the `trino` package and records what the bootstrap does."""

    def __init__(self):
        self.connect_kwargs = []
        self.statements = []

    def connect(self, **kwargs):
        self.connect_kwargs.append(kwargs)
        return _FakeConn(self)


@pytest.fixture
def trino_recorder(monkeypatch):
    recorder = _TrinoRecorder()
    module = types.ModuleType("trino")
    module.dbapi = types.SimpleNamespace(connect=recorder.connect)
    monkeypatch.setitem(sys.modules, "trino", module)
    return recorder


def test_skips_trino_entirely_when_feature_disabled(monkeypatch, trino_recorder):
    from app.medallion_init import init_medallion_namespaces

    monkeypatch.setenv("FEATURE_TRINO", "false")

    assert init_medallion_namespaces(logging.getLogger(__name__)) is False
    assert trino_recorder.connect_kwargs == []
    assert trino_recorder.statements == []


def test_skips_when_feature_unset(monkeypatch, trino_recorder):
    """Fail-closed, matching /api/capabilities' FEATURE_TRINO default."""
    from app.medallion_init import init_medallion_namespaces

    monkeypatch.delenv("FEATURE_TRINO", raising=False)

    assert init_medallion_namespaces(logging.getLogger(__name__)) is False
    assert trino_recorder.connect_kwargs == []


def test_creates_the_three_namespaces_when_trino_enabled(monkeypatch, trino_recorder):
    from app.medallion_init import init_medallion_namespaces

    monkeypatch.setenv("FEATURE_TRINO", "true")

    assert init_medallion_namespaces(logging.getLogger(__name__)) is True
    assert len(trino_recorder.connect_kwargs) == 1
    assert trino_recorder.statements == [
        "CREATE SCHEMA IF NOT EXISTS iceberg.raw",
        "CREATE SCHEMA IF NOT EXISTS iceberg.refined",
        "CREATE SCHEMA IF NOT EXISTS iceberg.serving",
    ]


def test_uses_trino_service_env_for_host_and_port(monkeypatch, trino_recorder):
    from app.medallion_init import init_medallion_namespaces

    monkeypatch.setenv("FEATURE_TRINO", "true")
    monkeypatch.setenv("TRINO_SERVICE_HOST", "trino.other.svc")
    monkeypatch.setenv("TRINO_SERVICE_PORT", "9090")

    init_medallion_namespaces(logging.getLogger(__name__))

    assert trino_recorder.connect_kwargs[0]["host"] == "trino.other.svc"
    assert trino_recorder.connect_kwargs[0]["port"] == 9090


def test_survives_a_trino_connection_failure(monkeypatch):
    """A reachable-but-broken Trino must not abort startup."""
    from app.medallion_init import init_medallion_namespaces

    monkeypatch.setenv("FEATURE_TRINO", "true")
    module = types.ModuleType("trino")

    def _boom(**kwargs):
        raise OSError("Name or service not known")

    module.dbapi = types.SimpleNamespace(connect=_boom)
    monkeypatch.setitem(sys.modules, "trino", module)

    assert init_medallion_namespaces(logging.getLogger(__name__)) is True
