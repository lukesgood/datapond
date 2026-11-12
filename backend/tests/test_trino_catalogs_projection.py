"""Projecting Trino-backed connections into the two Secrets Trino reads, restarting the
engine only when something changed, and reporting whether it is back (Phase 2 plan,
Task 3; Review Focus 4)."""
import asyncio

import pytest

from app.connectors import trino_catalogs as tc


class FakeKube:
    def __init__(self, secrets=None, replicas=1, ready=1, updated=1, annotations=None):
        self.secrets = {k: dict(v) for k, v in (secrets or {}).items()}
        self.patches, self.annotations = [], dict(annotations or {})
        self.replicas, self.ready, self.updated = replicas, ready, updated

    def read_secret_data(self, name):
        return dict(self.secrets.get(name, {}))

    def patch_secret_data(self, name, data):
        self.patches.append((name, dict(data)))
        cur = self.secrets.setdefault(name, {})
        for k, v in data.items():
            if v is None:
                cur.pop(k, None)
            else:
                cur[k] = v

    def patch_deployment_annotation(self, name, key, value):
        self.annotations[key] = value

    def deployment_status(self, name):
        return {"replicas": self.replicas, "ready_replicas": self.ready,
                "updated_replicas": self.updated, "annotations": dict(self.annotations)}


ROW = {"catalog": "src_crm", "connector_type": "postgresql",
       "config": {"host": "h", "port": 5432, "database": "d", "username": "u", "password": "s3cr;t"}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TRINO_SOURCE_CATALOGS_SECRET", "trino-source-catalogs")
    monkeypatch.setenv("TRINO_SOURCE_CREDENTIALS_SECRET", "trino-source-credentials")
    monkeypatch.setenv("TRINO_DEPLOYMENT", "trino")


def test_desired_state_has_one_file_and_one_env_per_trino_row():
    d = tc.desired_from_rows([ROW, {**ROW, "catalog": None}, {**ROW, "connector_type": "rest_api"}])
    assert set(d.catalogs) == {"src_crm.properties"}
    assert d.credentials == {"SRC_CRM_PASSWORD": "s3cr;t"}
    assert "s3cr;t" not in d.catalogs["src_crm.properties"]


def test_a_database_url_row_is_normalised_before_rendering():
    row = {"catalog": "src_fin", "connector_type": "database_url",
           "config": {"database_url": "postgresql://u:p@h:5432/fin"}}
    d = tc.desired_from_rows([row])
    assert "connector.name=postgresql" in d.catalogs["src_fin.properties"]
    assert d.credentials == {"SRC_FIN_PASSWORD": "p"}


def test_apply_patches_only_when_something_differs_and_removes_stale_keys():
    kube = FakeKube(secrets={"trino-source-catalogs": {"src_old.properties": "x"},
                             "trino-source-credentials": {"SRC_OLD_PASSWORD": "y"}})
    d = tc.desired_from_rows([ROW])
    assert tc.apply(d, kube) is True
    assert kube.secrets["trino-source-catalogs"].keys() == {"src_crm.properties"}
    assert kube.secrets["trino-source-credentials"] == {"SRC_CRM_PASSWORD": "s3cr;t"}
    kube.patches.clear()
    assert tc.apply(d, kube) is False and kube.patches == []


def test_restart_sets_the_annotation_and_status_reports_restarting_until_ready():
    kube = FakeKube(replicas=1, ready=0, updated=0)
    from datetime import datetime, timezone
    tc.restart(kube, now="2026-11-10T01:02:03Z")
    assert kube.annotations["datapond.io/source-catalogs-restarted-at"] == "2026-11-10T01:02:03Z"
    now = datetime(2026, 11, 10, 1, 2, 40, tzinfo=timezone.utc)
    s = tc.engine_status(kube, now=now)
    assert s == {"engine": "trino", "ready": False, "restarting": True,
                 "restarted_at": "2026-11-10T01:02:03Z"}
    kube.ready = kube.updated = 1
    s = tc.engine_status(kube, now=now)
    assert s["restarting"] is False and s["ready"] is True


def test_status_says_none_when_the_profile_has_no_trino(monkeypatch):
    monkeypatch.delenv("TRINO_SOURCE_CATALOGS_SECRET")
    assert tc.engine_status(FakeKube()) == {"engine": "none", "ready": False,
                                            "restarting": False, "restarted_at": None}


def test_a_row_whose_config_cannot_render_is_skipped_without_leaking_it(caplog):
    bad = {**ROW, "catalog": "src_bad", "config": {**ROW["config"], "host": "h\nconnector.name=memory"}}
    with caplog.at_level("WARNING"):
        d = tc.desired_from_rows([ROW, bad])
    assert set(d.catalogs) == {"src_crm.properties"}
    assert "src_bad" in caplog.text and "memory" not in caplog.text and "s3cr;t" not in caplog.text


def test_project_converges_when_run_twice_and_restarts_once(monkeypatch):
    kube = FakeKube()

    async def rows(_pool):
        return [ROW]
    monkeypatch.setattr(tc, "load_rows", rows)
    first = asyncio.run(tc.project(pool=None, kube=kube))
    second = asyncio.run(tc.project(pool=None, kube=kube))
    assert first == {"changed": True, "catalogs": ["src_crm"]}
    assert second == {"changed": False, "catalogs": ["src_crm"]}
    assert list(kube.annotations) == ["datapond.io/source-catalogs-restarted-at"]


def test_project_can_skip_the_restart(monkeypatch):
    kube = FakeKube()

    async def rows(_pool):
        return [ROW]
    monkeypatch.setattr(tc, "load_rows", rows)
    asyncio.run(tc.project(pool=None, kube=kube, restart_if_changed=False))
    assert kube.annotations == {} and kube.secrets["trino-source-catalogs"]


def test_project_is_a_no_op_on_a_profile_without_trino(monkeypatch):
    monkeypatch.delenv("TRINO_SOURCE_CATALOGS_SECRET")
    kube = FakeKube()
    out = asyncio.run(tc.project(pool=None, kube=kube))
    assert out == {"changed": False, "catalogs": []} and kube.patches == []


# ── rows from the database: the vault is the source of truth ──────────────────

class _Conn:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *args):
        return self.rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, rows):
        self.rows = rows

    def acquire(self):
        return _Conn(self.rows)


def test_load_rows_decrypts_with_the_vault_and_skips_what_it_cannot(monkeypatch, caplog):
    from app.connectors.vault import CredentialVault
    monkeypatch.setenv("ENCRYPTION_KEY", "k" * 32)
    good = CredentialVault("k" * 32).encrypt_credentials(ROW["config"])
    stale = CredentialVault("old-key-from-a-previous-cluster").encrypt_credentials(ROW["config"])
    pool = _Pool([
        {"id": "1", "name": "CRM", "connector_type": "postgresql", "catalog": "src_crm", "config_encrypted": good},
        {"id": "2", "name": "Legacy", "connector_type": "postgresql", "catalog": "src_legacy", "config_encrypted": stale},
    ])
    with caplog.at_level("WARNING"):
        rows = asyncio.run(tc.load_rows(pool))
    assert [r["catalog"] for r in rows] == ["src_crm"]
    assert rows[0]["config"]["password"] == "s3cr;t"
    assert "src_legacy" in caplog.text and "s3cr;t" not in caplog.text and stale not in caplog.text


def test_a_new_catalog_s_password_lands_before_its_file_and_leaves_after_it():
    """A catalog file naming ${ENV:…} that the credentials Secret lacks stops the whole
    engine at its next start (review finding 7): credentials are added first and
    removed last, so no sequence of partial failures leaves a dangling reference."""
    kube = FakeKube(secrets={"trino-source-catalogs": {"src_old.properties": "x"},
                             "trino-source-credentials": {"SRC_OLD_PASSWORD": "y"}})
    tc.apply(tc.desired_from_rows([ROW]), kube)
    order = [(name, sorted(k for k, v in data.items() if v is not None),
              sorted(k for k, v in data.items() if v is None)) for name, data in kube.patches]
    assert order == [("trino-source-credentials", ["SRC_CRM_PASSWORD"], []),
                     ("trino-source-catalogs", ["src_crm.properties"], ["src_old.properties"]),
                     ("trino-source-credentials", [], ["SRC_OLD_PASSWORD"])]


def test_an_old_restart_stamp_does_not_make_later_unreadiness_a_restart():
    """restarting means our rollout is in progress; an engine that fell over an hour
    after it is not-ready, so the console says so instead of 'restarting (~1 min)'
    and the sample activation does not wait on it (review finding 8)."""
    from datetime import datetime, timezone
    kube = FakeKube(replicas=1, ready=0, updated=1,
                    annotations={"datapond.io/source-catalogs-restarted-at": "2026-11-10T01:00:00Z"})
    soon = datetime(2026, 11, 10, 1, 3, 0, tzinfo=timezone.utc)
    later = datetime(2026, 11, 10, 2, 0, 0, tzinfo=timezone.utc)
    assert tc.engine_status(kube, now=soon)["restarting"] is True
    s = tc.engine_status(kube, now=later)
    assert s["restarting"] is False and s["ready"] is False


def test_project_holds_an_advisory_lock_around_the_patches(monkeypatch):
    """Two replicas (or create + startup) projecting at once both saw a diff and bumped
    the annotation twice — two restarts (deferred minor #10). The projection now runs
    under a session advisory lock, so the second waits and finds nothing to change."""
    calls = []

    class Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, sql, *args):
            calls.append(sql)

    class Pool:
        def acquire(self):
            return Conn()

    async def rows(_pool):
        calls.append("rows")
        return [ROW]
    monkeypatch.setattr(tc, "load_rows", rows)
    monkeypatch.setattr(tc, "_ensure_rows", None)
    out = asyncio.run(tc.project(pool=Pool(), kube=FakeKube()))
    assert out["changed"] is True
    assert len(calls) == 3 and "pg_advisory_lock(" in calls[0] and calls[1] == "rows" \
        and "pg_advisory_unlock(" in calls[2]


def test_a_restart_also_restarts_the_workers_when_there_are_any(monkeypatch):
    """Workers read the catalog files at startup too: a new source catalog on the
    coordinator alone would fail every query scheduled on a worker."""
    kube = FakeKube()
    calls = []
    kube.patch_deployment_annotation = lambda name, key, value: calls.append((name, key, value))
    monkeypatch.setenv("TRINO_WORKER_DEPLOYMENT", "trino-worker")
    tc.restart(kube, now="2026-11-12T01:00:00Z")
    assert [c[0] for c in calls] == ["trino", "trino-worker"]
    calls.clear()
    monkeypatch.delenv("TRINO_WORKER_DEPLOYMENT")
    tc.restart(kube, now="2026-11-12T01:00:00Z")
    assert [c[0] for c in calls] == ["trino"]


def test_the_engine_is_ready_only_when_the_workers_are_back_too(monkeypatch):
    """With workers the coordinator only plans; a query before they return fails with
    no nodes to run on, so 'ready' must wait for them."""
    from datetime import datetime, timezone
    states = {"trino": {"replicas": 1, "ready_replicas": 1, "updated_replicas": 1,
                        "annotations": {"datapond.io/source-catalogs-restarted-at": "2026-11-12T01:00:00Z"}},
              "trino-worker": {"replicas": 2, "ready_replicas": 1, "updated_replicas": 2, "annotations": {}}}
    kube = FakeKube()
    kube.deployment_status = lambda name: states[name]
    monkeypatch.setenv("TRINO_WORKER_DEPLOYMENT", "trino-worker")
    now = datetime(2026, 11, 12, 1, 1, 0, tzinfo=timezone.utc)
    s = tc.engine_status(kube, now=now)
    assert s["ready"] is False and s["restarting"] is True
    states["trino-worker"]["ready_replicas"] = 2
    s = tc.engine_status(kube, now=now)
    assert s["ready"] is True and s["restarting"] is False
