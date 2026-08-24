"""/ai/sql must never hand back something it has not checked.

Three failure modes seen live: an empty catalog still burned an LLM call; a prose
reply came back flagged has_ai=true with a sentence in `sql`; and nothing verified
the generated SQL against the real catalog before the user ran it.
"""
import asyncio

import pytest

import app.api.ai_sql as m

USER = {"id": "00000000-0000-0000-0000-0000000000aa", "username": "admin", "role": "admin"}
SCHEMA = "Available tables (catalog: AwsDataCatalog):\n  AwsDataCatalog.sales.orders: id (int), amt (double)"


def _run(req):
    return asyncio.run(m.generate_sql(req, user=USER))


@pytest.fixture
def gateway(monkeypatch):
    """Configured gateway + a populated catalog, so only the reply under test varies."""
    monkeypatch.setattr(m, "_cfg", lambda: {
        "litellm_url": "http://litellm:4000", "litellm_model": "default", "master_key": "",
    })
    monkeypatch.setattr(m, "_get_schema_context", lambda: SCHEMA)
    monkeypatch.setattr(m, "egress_policy", lambda: "allow-external")
    monkeypatch.setattr(m, "validate_sql", lambda sql: (True, None))
    return monkeypatch


def test_empty_catalog_short_circuits_without_calling_the_model(monkeypatch):
    called = []
    monkeypatch.setattr(m, "_cfg", lambda: {
        "litellm_url": "http://litellm:4000", "litellm_model": "default", "master_key": "",
    })
    monkeypatch.setattr(m, "_get_schema_context", lambda: "No tables found in the catalog.")
    monkeypatch.setattr(m, "_call_litellm", lambda s, msgs: called.append(1) or "{}")

    res = _run(m.AskRequest(question="지역별 합계"))

    assert called == [], "no catalog means nothing to generate against — do not spend a call"
    assert res.sql == ""
    assert res.needs_input is True
    assert "catalog" in res.provider


def test_prose_reply_returns_no_sql_and_keeps_the_models_words(gateway):
    prose = "I need more information. Which table holds the order amounts?"
    gateway.setattr(m, "_call_litellm", lambda s, msgs: prose)

    res = _run(m.AskRequest(question="지역별 합계"))

    assert res.sql == "", "a clarifying question is not SQL"
    assert res.needs_input is True
    assert res.has_ai is True, "the model did answer — this is not a missing-backend case"
    assert "which table" in res.explanation.lower()


def test_valid_sql_is_returned_and_marked_validated(gateway):
    gateway.setattr(m, "_call_litellm",
                    lambda s, msgs: '{"sql": "SELECT 1", "explanation": "one"}')

    res = _run(m.AskRequest(question="하나"))

    assert res.sql == "SELECT 1"
    assert res.validated is True
    assert res.needs_input is False


def test_invalid_sql_is_retried_once_with_the_engine_error(monkeypatch):
    """A hallucinated column is exactly what EXPLAIN (TYPE VALIDATE) catches."""
    monkeypatch.setattr(m, "_cfg", lambda: {
        "litellm_url": "http://litellm:4000", "litellm_model": "default", "master_key": "",
    })
    monkeypatch.setattr(m, "_get_schema_context", lambda: SCHEMA)
    monkeypatch.setattr(m, "egress_policy", lambda: "allow-external")

    replies = ['{"sql": "SELECT nope FROM sales.orders", "explanation": "bad"}',
               '{"sql": "SELECT amt FROM sales.orders", "explanation": "good"}']
    seen_prompts = []

    def _call(system, messages):
        seen_prompts.append(messages[-1]["content"])
        return replies[len(seen_prompts) - 1]

    def _validate(sql):
        if "nope" in sql:
            return False, "COLUMN_NOT_FOUND: Column 'nope' cannot be resolved"
        return True, None

    monkeypatch.setattr(m, "_call_litellm", _call)
    monkeypatch.setattr(m, "validate_sql", _validate)

    res = _run(m.AskRequest(question="금액"))

    assert len(seen_prompts) == 2, "the engine error must be fed back once"
    assert "COLUMN_NOT_FOUND" in seen_prompts[1]
    assert res.sql == "SELECT amt FROM sales.orders"
    assert res.validated is True


def test_sql_that_stays_invalid_is_returned_but_flagged(monkeypatch):
    monkeypatch.setattr(m, "_cfg", lambda: {
        "litellm_url": "http://litellm:4000", "litellm_model": "default", "master_key": "",
    })
    monkeypatch.setattr(m, "_get_schema_context", lambda: SCHEMA)
    monkeypatch.setattr(m, "egress_policy", lambda: "allow-external")
    monkeypatch.setattr(m, "_call_litellm",
                        lambda s, msgs: '{"sql": "SELECT nope FROM sales.orders", "explanation": "x"}')
    monkeypatch.setattr(m, "validate_sql", lambda sql: (False, "COLUMN_NOT_FOUND: nope"))

    res = _run(m.AskRequest(question="금액"))

    assert res.validated is False
    assert "COLUMN_NOT_FOUND" in (res.validation_error or "")
    assert res.sql, "still show it — the user may want to fix it by hand"


def test_no_gateway_configured_still_reports_the_template_fallback(monkeypatch):
    monkeypatch.setattr(m, "_cfg", lambda: {
        "litellm_url": "", "litellm_model": "default", "master_key": "",
    })
    monkeypatch.setattr(m, "_get_schema_context", lambda: SCHEMA)

    res = _run(m.AskRequest(question="금액"))

    assert res.has_ai is False
    assert res.provider == "none"
