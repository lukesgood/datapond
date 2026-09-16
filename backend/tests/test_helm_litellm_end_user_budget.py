"""A deployment can hold every caller to a default model spend cap.

Per-caller caps are enforced by the gateway against the end user DataPond stamps on
each call. Without a default, a caller has no cap until an operator sets one — which
means a freshly issued agent key spends unmetered until someone notices.
"""
import re
import subprocess
from pathlib import Path

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"


def render(*sets):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond"]
    for s in sets:
        cmd += ["--set", s]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _litellm_config(rendered: str) -> str:
    m = re.search(r"config\.yaml: \|(.*?)\n---", rendered, re.S)
    assert m, "litellm config.yaml not rendered"
    return m.group(1)


def test_unset_means_no_default_cap():
    assert "max_end_user_budget_id" not in _litellm_config(render())


def test_setting_it_holds_every_caller_to_that_budget():
    cfg = _litellm_config(render("litellm.endUserBudgetId=default-caller-budget"))
    assert 'max_end_user_budget_id: "default-caller-budget"' in cfg
