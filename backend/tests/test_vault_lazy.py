"""Importing the connector routes must not build the credential vault.

The migration Job imports app.api.connectors for its pool helper only, and has no
ENCRYPTION_KEY: every live migration logged "ENCRYPTION_KEY unset — using an insecure
local-dev key. NOT for production." — a false alarm in the one log that records what a
release did to the database."""
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _run(code: str, **env):
    e = {k: v for k, v in os.environ.items() if k not in ("ENCRYPTION_KEY", "ENVIRONMENT")}
    e.update(env)
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=e,
                          capture_output=True, text=True, timeout=120)


def test_importing_the_connector_routes_does_not_touch_the_key():
    r = _run("import logging; logging.basicConfig(level=logging.WARNING); import app.api.connectors")
    assert r.returncode == 0, r.stderr[-800:]
    assert "ENCRYPTION_KEY" not in r.stderr


def test_the_vault_is_built_on_first_use_and_round_trips():
    r = _run("import app.api.connectors as c; "
             "print(c.vault.decrypt_credentials(c.vault.encrypt_credentials({'a': 1})))",
             ENCRYPTION_KEY="k" * 32)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip() == "{'a': 1}"
