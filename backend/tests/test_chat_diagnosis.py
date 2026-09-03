"""The shape every diagnostic returns.

Facts are measured, signals are judged, and not_checked is what was out of reach. The
model narrates all three; it decides none of them.
"""
import pytest

from app.chat.diagnosis import Diagnosis


def test_it_carries_subject_facts_signals_and_gaps():
    d = Diagnosis("collection 'handbook'")
    d.fact("chunks", 412)
    d.signal("warn", "Last refreshed 9 days ago", last_refreshed_at="2026-08-25")
    d.skipped("Quality checks need the connectors add-on, which is off")
    out = d.done()

    assert out["subject"] == "collection 'handbook'"
    assert out["facts"] == {"chunks": 412}
    assert out["signals"] == [{"severity": "warn",
                               "statement": "Last refreshed 9 days ago",
                               "evidence": {"last_refreshed_at": "2026-08-25"}}]
    assert out["not_checked"] == ["Quality checks need the connectors add-on, which is off"]


def test_an_untouched_diagnosis_still_has_every_key():
    """The model reads the keys, not the presence of keys. A missing 'not_checked'
    would be indistinguishable from 'nothing was skipped'."""
    assert Diagnosis("x").done() == {
        "subject": "x", "facts": {}, "signals": [], "not_checked": []}


def test_severity_is_one_of_three_words():
    d = Diagnosis("x")
    with pytest.raises(ValueError):
        d.signal("critical", "…")


def test_signals_keep_the_order_they_were_added():
    d = Diagnosis("x")
    d.signal("ok", "first")
    d.signal("bad", "second")
    assert [s["statement"] for s in d.done()["signals"]] == ["first", "second"]
