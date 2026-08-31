"""Whether default-deny is safe to flip is a readout, not a guess.

`RLS_DEFAULT_DENY=false` lets any table with no policy through unfiltered.
`app/rls/coverage.py` already computes which tables those are, but nothing said so
anywhere an operator would look — not the readiness payload, not a startup log line.
An operator could enable RLS, watch nothing break, and read that as "the data is
governed" when it means "nothing has a policy yet, so nothing was checked."

`rls_posture` turns the three inputs that describe that situation (is RLS on, is
default-deny on, how many tables have no policy) into the one sentence that belongs
in `/health/ready`'s `state` dict next to `migrations` and `base_schema`. It must
never gate readiness — an advisory posture describes a real deployment, not a broken
one — so these tests drive a real `Readiness` object the way the readout is wired in
`main.py`, rather than asserting on the string in isolation.
"""
from app.readiness import Readiness
from app.rls.coverage import rls_posture


def test_rls_off_is_reported_as_off():
    assert rls_posture(rls_enabled=False, default_deny=False, uncovered=9) == "off"


def test_rls_off_is_reported_as_off_regardless_of_default_deny():
    """default_deny is meaningless while RLS itself is off — the engine never runs,
    so a stale `RLS_DEFAULT_DENY=true` left over from a previous config must not
    make this look like enforcement."""
    assert rls_posture(rls_enabled=False, default_deny=True, uncovered=0) == "off"


def test_default_deny_on_is_reported_as_enforcing():
    """With default-deny on, an unlisted table is refused rather than let through, so
    there is nothing left to warn about regardless of the uncovered count."""
    assert rls_posture(rls_enabled=True, default_deny=True, uncovered=9) == "enforcing"


def test_default_deny_off_names_the_uncovered_count():
    assert rls_posture(rls_enabled=True, default_deny=False, uncovered=9) == (
        "advisory (9 tables uncovered)"
    )


def test_default_deny_off_with_nothing_uncovered_still_reads_as_advisory():
    """Zero uncovered tables is not the same claim as `default_deny=true`: the next
    table added without a policy would pass through unfiltered here and would be
    refused there. Collapsing the two into the same word would hide that the safety
    net is still off, only currently untested."""
    assert rls_posture(rls_enabled=True, default_deny=False, uncovered=0) == (
        "advisory (0 tables uncovered)"
    )


# ── wired into /health/ready's state, the way main.py wires it ────────────────


def test_advisory_posture_reaches_the_readiness_state_dict():
    r = Readiness(required={"base_schema"})
    r.record("rls", ok=True, detail=rls_posture(rls_enabled=True, default_deny=False,
                                                 uncovered=3))
    assert r.status()["state"]["rls"] == "advisory (3 tables uncovered)"


def test_advisory_posture_with_uncovered_tables_does_not_fail_readiness():
    """This is a readout, not a gate. A deployment that has enabled RLS but not yet
    written policies for every table is not a broken deployment — it is one that
    has not decided to flip default-deny yet, which is a legitimate, even common,
    state. Failing readiness over it would make turning RLS on itself risky."""
    r = Readiness(required={"base_schema"})
    r.record("base_schema", ok=True)
    r.record("rls", ok=True, detail=rls_posture(rls_enabled=True, default_deny=False,
                                                 uncovered=42))
    status = r.status()
    assert status["ready"] is True
    assert status["state"]["rls"] == "advisory (42 tables uncovered)"


def test_enforcing_posture_also_reaches_the_state_dict():
    r = Readiness(required={"base_schema"})
    r.record("rls", ok=True, detail=rls_posture(rls_enabled=True, default_deny=True,
                                                 uncovered=0))
    assert r.status()["state"]["rls"] == "enforcing"


def test_off_posture_also_reaches_the_state_dict():
    r = Readiness(required={"base_schema"})
    r.record("rls", ok=True, detail=rls_posture(rls_enabled=False, default_deny=False,
                                                 uncovered=0))
    assert r.status()["state"]["rls"] == "off"
