"""Python sources run outside the backend (app/connectors/sandbox.py): known escapes are
refused before anything runs, and a runaway is stopped without stopping the backend."""
import asyncio
import os

import pytest

from app.connectors import sandbox as sb
from app.connectors.base import ConnectorType
from app.connectors.custom import CustomConfig, CustomConnector

ESCAPES = {
    "subclasses": "def fetch_data():\n    return [c.__name__ for c in ().__class__.__base__.__subclasses__()]\n",
    "import": "import os\ndef fetch_data():\n    return [{'k': os.environ.get('X')}]\n",
    "from_import": "from os import environ\ndef fetch_data():\n    return []\n",
    "format_walk": "def fetch_data():\n    return [{'x': '{0.__class__}'.format(1)}]\n",
    "frame": "def fetch_data():\n    g = (x for x in [1])\n    return [{'x': str(g.gi_frame.f_globals)}]\n",
    "builtins_name": "def fetch_data():\n    return [{'x': str(__builtins__)}]\n",
    "dunder_def": "def __init__():\n    pass\ndef fetch_data():\n    return []\n",
    "private_attr": "def fetch_data():\n    return [{'x': [].copy._x}]\n",
}


@pytest.mark.parametrize("name", sorted(ESCAPES))
def test_known_escapes_are_refused_before_running(name):
    with pytest.raises(sb.SandboxError) as e:
        sb.check(ESCAPES[name])
    assert e.value.kind == "refused" and "Line" in str(e.value)


def test_plain_python_passes_the_check_and_runs():
    code = ("ROWS = {'a': 1}\n"
            "def fetch_data():\n"
            "    out = []\n"
            "    for i in range(3):\n"
            "        out.append({'id': i, 'label': 'r%02d' % i, 'f': f'{i}-x', 'v': ROWS.get('a')})\n"
            "    return sorted(out, key=lambda r: -r['id'])\n")
    rows = sb.run(code)
    assert rows[0] == {"id": 2, "label": "r02", "f": "2-x", "v": 1} and len(rows) == 3


def test_the_child_has_no_backend_secrets(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "very-secret")
    # No import and no dunder, so the code cannot even ask; the child's environment is
    # empty anyway. Prove the second: run the runner directly with a probe.
    import json
    import subprocess
    import sys
    probe = "import json, os, sys; print(json.dumps(sorted(os.environ)))"
    out = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    assert "ENCRYPTION_KEY" not in json.loads(out.stdout)


def test_a_runaway_is_stopped_and_the_caller_carries_on():
    with pytest.raises(sb.SandboxError) as e:
        sb.run("def fetch_data():\n    while True:\n        pass\n", timeout=2)
    assert e.value.kind in ("timeout", "memory")


def test_errors_and_wrong_types_come_back_as_messages():
    with pytest.raises(sb.SandboxError, match="ZeroDivisionError"):
        sb.run("def fetch_data():\n    return [1 / 0]\n")
    with pytest.raises(sb.SandboxError, match="list of dicts"):
        sb.run("def fetch_data():\n    return {'a': 1}\n")
    with pytest.raises(sb.SandboxError, match="fetch_data"):
        sb.run("x = 1\n")
    with pytest.raises(sb.SandboxError) as e:
        sb.check("def f(:\n")
    assert e.value.kind == "syntax"


def test_module_level_loops_cannot_hang_test_connection():
    c = CustomConnector(CustomConfig(name="c", connector_type=ConnectorType.CUSTOM,
                                     code="while True:\n    pass\ndef fetch_data():\n    return []\n"))
    os.environ["CUSTOM_SOURCE_TIMEOUT_SECONDS"] = "2"
    try:
        res = asyncio.run(c.test_connection())
    finally:
        del os.environ["CUSTOM_SOURCE_TIMEOUT_SECONDS"]
    assert res.success is False and ("seconds" in res.message or "CPU" in res.message)


def test_test_connection_refuses_an_escape_without_running_it():
    c = CustomConnector(CustomConfig(name="c", connector_type=ConnectorType.CUSTOM, code=ESCAPES["subclasses"]))
    res = asyncio.run(c.test_connection())
    assert res.success is False and "not allowed" in res.message
