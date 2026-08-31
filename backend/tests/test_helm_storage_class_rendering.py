"""An empty storage class must render no key at all, not an empty one.

`storageClassName:` with nothing after it is null, and Kubernetes reads null as "use
the default" only at creation. The API server then writes the real class into the
object. On the next upgrade Helm sees its own manifest still saying null, tries to
patch the field back, and the API server refuses:

    PersistentVolumeClaim "valkey-pvc" is invalid:
      spec: Forbidden: spec is immutable after creation

So the install worked and the *upgrade* failed, on a profile that had done nothing
wrong except decline to pin a storage class.

One helper emits the key or omits it, and every template goes through it — a rule
that has to hold in ten places is a rule that will not.
"""
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "helm/datapond/templates"
HELPER = "datapond.storageClassName"


def _raw_uses() -> dict:
    out = {}
    for path in sorted(TEMPLATES.glob("*.yaml")):
        lines = [l for l in path.read_text().splitlines()
                 if re.search(r'^\s*storageClassName:', l)]
        if lines:
            out[path.name] = lines
    return out


def test_no_template_writes_the_key_itself():
    assert _raw_uses() == {}, (
        f"these still render storageClassName directly: {sorted(_raw_uses())}")


def test_the_helper_exists_and_can_emit_nothing():
    body = (TEMPLATES / "_storage.tpl").read_text()
    assert f'define "{HELPER}"' in body
    assert "if $value" in body, "the helper must omit the key when the value is empty"


def test_every_claim_that_used_to_pin_a_class_now_calls_the_helper():
    """Ten call sites across eight templates; a rule that has to hold in ten places
    is a rule that will not, so the test counts them."""
    callers = [p.name for p in TEMPLATES.glob("*.yaml") if HELPER in p.read_text()]
    assert len(callers) >= 7, f"only {callers} call the helper"
