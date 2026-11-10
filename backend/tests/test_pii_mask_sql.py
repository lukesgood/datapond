"""PII masking at ingest moves into the INSERT … SELECT Trino runs: the same Korean
patterns pii_ko masks in Python, as a regexp_replace chain (Phase 2 plan, Task 6)."""
from app.guardrails import pii_ko


def test_mask_sql_chains_one_regexp_replace_per_pattern_with_the_same_labels():
    sql = pii_ko.mask_sql('"memo"')
    assert sql.count("regexp_replace(") == len(pii_ko._PATTERNS)
    for label, _rx, _v in pii_ko._PATTERNS:
        assert f"'[{label}]'" in sql
    assert sql.startswith("regexp_replace(") and 'CAST("memo" AS VARCHAR)' in sql


def test_every_pattern_appears_verbatim_with_single_quotes_doubled():
    sql = pii_ko.mask_sql("c")
    for _l, rx, _v in pii_ko._PATTERNS:
        assert rx.pattern.replace("'", "''") in sql
    # The patterns carry no quote today; the escaping rule is what keeps the SQL whole
    # if one ever does.
    assert pii_ko.mask_sql("c").count("'") % 2 == 0


def test_the_patterns_are_valid_java_style_regexes():
    """Trino's regexp functions take Java/Joni syntax; every construct the patterns use
    (\\d \\b \\w \\s, (?:…), {m,n}, classes) exists there. A pattern that Python accepts
    but Java would not — a lookbehind of unbounded width, a possessive quantifier
    Python lacks — is what this guards against."""
    import re
    forbidden = re.compile(r"\(\?<[=!]|\(\?P<|\\Z|\\A|\(\?[imsx]+\)")
    for _l, rx, _v in pii_ko._PATTERNS:
        assert not forbidden.search(rx.pattern), rx.pattern
