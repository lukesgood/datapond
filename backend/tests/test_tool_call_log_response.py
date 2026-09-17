"""The log records what came back, not only what was asked.

"What did this caller receive" is the first question an audit asks of a system under
personal-data obligations, and until 0013 the table could not answer it: it held the
request, the hit count and the cited sources, and nothing about the response.
"""
from app import tool_call_log as tcl

ACTOR = {"id": None, "username": "u", "auth_method": "local"}


def _row(**kw):
    base = dict(actor=ACTOR, tool="ai.rag", resource_kind="collection",
                resource=["c"], request_text="q")
    base.update(kw)
    return tcl.build_row(**base)


def test_no_response_stays_null():
    """A call that records no response must not read as one that returned nothing."""
    row = _row()
    assert row["response_hash"] is None and row["response_masked"] is None


def test_empty_response_is_recorded_as_empty():
    row = _row(response_text="")
    assert row["response_masked"] == ""
    assert row["response_hash"] is not None


def test_response_is_masked_before_it_is_stored():
    row = _row(response_text="연락처는 010-1234-5678 입니다")
    assert "010-1234-5678" not in row["response_masked"]
    assert "[휴대전화]" in row["response_masked"]


def test_a_credential_in_the_response_is_masked_too():
    row = _row(response_text="use AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in row["response_masked"]


def test_masking_ignores_the_guardrail_mode(monkeypatch):
    """The caller's mode decides what the caller gets; the log is never raw."""
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "off")
    row = _row(response_text="연락처는 010-1234-5678 입니다")
    assert "010-1234-5678" not in row["response_masked"]


def test_hash_covers_the_full_text_not_the_excerpt():
    long_tail = "x" * (tcl._MASKED_LIMIT + 50)
    a = _row(response_text="head " + long_tail)
    b = _row(response_text="head " + long_tail + "different ending")
    assert len(a["response_masked"]) <= tcl._MASKED_LIMIT
    assert a["response_masked"] == b["response_masked"], "excerpts collide after truncation"
    assert a["response_hash"] != b["response_hash"], "the digest must still tell them apart"
