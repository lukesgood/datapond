"""Valkey needs three capabilities to become non-root, not two.

`drop: ALL` is not safe for an image whose entrypoint starts as root and lowers
itself. Valkey's does three things on the way down, and each one was found by taking
the next capability away:

  setpriv  → SETUID, SETGID   (found 2026-08; CrashLoop, "setresuid failed")
  chown    → CHOWN            (found 2026-08-27; CrashLoop, "changing ownership of
                               '.': Operation not permitted")

The second hid behind the first: with SETUID and SETGID missing the entrypoint never
reached the chown, and the live pod predated the hardening entirely, so it ran for two
days without it ever applying. The first fresh install after the outage was the first
time this container actually started under the policy.

Three capabilities out of fourteen is still the hardening. Zero would be better and
means running as the image's own UID instead — a change that needs that UID confirmed
against the image, not guessed.
"""
from pathlib import Path

TEMPLATE = (Path(__file__).resolve().parents[2]
            / "helm/datapond/templates/valkey-deployment.yaml")


def test_valkey_keeps_the_capabilities_its_entrypoint_uses():
    body = TEMPLATE.read_text()
    line = next(l for l in body.splitlines() if "datapond.containerSecurity" in l)
    for capability in ("SETUID", "SETGID", "CHOWN"):
        assert capability in line, f"valkey will CrashLoop without {capability}: {line}"


def test_nothing_else_is_kept():
    """The list is what the entrypoint needs, not a convenient allowance."""
    line = next(l for l in TEMPLATE.read_text().splitlines()
                if "datapond.containerSecurity" in l)
    for capability in ("NET_ADMIN", "SYS_ADMIN", "DAC_OVERRIDE", "ALL"):
        assert capability not in line, f"{capability} is not needed to become non-root"
