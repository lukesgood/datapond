"""Model replies are untrusted text. The parser must recover SQL when it is there
and refuse to invent it when it is not.

Live reproduction (2026-08-24): with an empty catalog the model replied in prose
asking for the table structure. The parser matched the English word "with", cut
from it, and returned a sentence fragment as runnable SQL flagged has_ai=true.
"""
import pytest

from app.api.ai_sql import _parse_response


# ── must NOT fabricate SQL out of prose ───────────────────────────────────────

PROSE_REPLY = (
    "I need more information. Do you have a single table with columns like "
    "region, order_amount? Or separate tables that need to be joined?"
)


def test_prose_reply_raises_instead_of_fabricating_sql():
    with pytest.raises(ValueError):
        _parse_response(PROSE_REPLY)


@pytest.mark.parametrize("prose", [
    "I need more information. Do you have a table with columns like region?",
    "Please select a table first, then ask again.",
    "Could you describe the schema you want to query?",
    "I can show you the totals once you tell me the table name.",
    "You would create a view for that, but no table exists yet.",
    "Update your catalog first — nothing is registered.",
])
def test_english_sql_keywords_in_prose_are_not_sql(prose):
    """SELECT / SHOW / DESCRIBE / CREATE / UPDATE / WITH are ordinary English words."""
    with pytest.raises(ValueError):
        _parse_response(prose)


# ── must still recover SQL in every shape the models actually emit ────────────

def test_clean_json_reply():
    out = _parse_response('{"sql": "SELECT 1", "explanation": "returns one"}')
    assert out["sql"] == "SELECT 1"
    assert out["explanation"] == "returns one"


def test_json_with_literal_newlines_inside_the_string():
    """Models emit multi-line SQL unescaped; strict json.loads rejects it."""
    out = _parse_response('{"sql": "SELECT a\nFROM t", "explanation": "multi-line"}')
    assert "SELECT a" in out["sql"] and "FROM t" in out["sql"]


def test_fenced_json_reply():
    out = _parse_response('```json\n{"sql": "SELECT 2", "explanation": "two"}\n```')
    assert out["sql"] == "SELECT 2"


def test_fenced_bare_sql_reply():
    out = _parse_response("```sql\nSELECT 3 FROM t\n```")
    assert out["sql"].startswith("SELECT 3")


def test_bare_sql_reply_with_no_wrapper():
    out = _parse_response("SELECT id, name FROM sales.orders ORDER BY id")
    assert out["sql"].startswith("SELECT id, name FROM sales.orders")


def test_sql_after_a_prose_preamble():
    out = _parse_response("Here is the query you asked for:\nSELECT count(*) FROM sales.orders")
    assert out["sql"].startswith("SELECT count(*)")


def test_prose_around_a_json_object():
    out = _parse_response('Sure!\n{"sql": "SELECT 4", "explanation": "four"}\nHope that helps.')
    assert out["sql"] == "SELECT 4"


def test_double_wrapped_json_is_unwrapped():
    inner = '{\\"sql\\": \\"SELECT 5\\", \\"explanation\\": \\"five\\"}'
    out = _parse_response('{"sql": "' + inner + '", "explanation": ""}')
    assert out["sql"] == "SELECT 5"


def test_malformed_json_wrapper_with_unescaped_trino_identifiers():
    """The case _salvage_sql was written for (#66-69): double-quoted Trino
    identifiers break the JSON, but a wrapper is clearly present."""
    raw = '{"sql": "SELECT "region" FROM sales.orders", "explanation": "by region"}'
    out = _parse_response(raw)
    assert out["sql"].startswith("SELECT ")
    assert "region" in out["sql"]
    assert "explanation" not in out["sql"]


def test_with_cte_is_recognised_as_sql():
    out = _parse_response("WITH recent AS (SELECT * FROM t) SELECT * FROM recent")
    assert out["sql"].startswith("WITH recent")
