"""The post-deploy check that the Secrets Manager vault still matches the cluster's
critical secrets (scripts/check_secrets_mirror.py; the 2026-11-10 stale-mirror incident)."""
import base64
import importlib.util
import json
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_secrets_mirror", Path(__file__).resolve().parents[2] / "scripts/check_secrets_mirror.py")
csm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(csm)

CLUSTER = {"ENCRYPTION_KEY": "k1", "JWT_SECRET": "j", "INTERNAL_API_KEY": "i", "ADMIN_PASSWORD": "a"}


def test_compare_names_keys_never_values():
    differs, missing, not_mirrored, matching = csm.compare(
        CLUSTER, {"ENCRYPTION_KEY": "OLD", "JWT_SECRET": "j", "POLARIS_TOKEN_KEY": "p"})
    assert differs == ["ENCRYPTION_KEY"] and missing == ["POLARIS_TOKEN_KEY"]
    assert not_mirrored == ["INTERNAL_API_KEY"] and matching == ["JWT_SECRET"]


def _fake_run(vault, vault_rc=0):
    data = {k: base64.b64encode(v.encode()).decode() for k, v in CLUSTER.items()}

    def run(cmd):
        if cmd[0] == "kubectl":
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": data}), "")
        if vault_rc:
            return subprocess.CompletedProcess(cmd, vault_rc, "", "An error occurred (AccessDeniedException)")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(vault), "")
    return run


def test_a_stale_vault_fails_the_deploy_without_printing_values(monkeypatch, capsys):
    monkeypatch.setattr(csm, "_run", _fake_run({"ENCRYPTION_KEY": "OLD-SECRET", "JWT_SECRET": "j",
                                                 "INTERNAL_API_KEY": "i"}))
    assert csm.main([]) == 1
    out = capsys.readouterr().out
    assert "::error::" in out and "ENCRYPTION_KEY" in out
    assert "OLD-SECRET" not in out and "k1" not in out


def test_a_matching_vault_passes(monkeypatch, capsys):
    monkeypatch.setattr(csm, "_run", _fake_run({"ENCRYPTION_KEY": "k1", "JWT_SECRET": "j", "INTERNAL_API_KEY": "i"}))
    assert csm.main([]) == 0
    assert "3 key(s) match" in capsys.readouterr().out


def test_an_unreadable_vault_warns_but_does_not_fail(monkeypatch, capsys):
    monkeypatch.setattr(csm, "_run", _fake_run({}, vault_rc=255))
    assert csm.main([]) == 0
    assert "::warning::" in capsys.readouterr().out
