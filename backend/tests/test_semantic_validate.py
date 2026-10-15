"""What a metric definition may contain. Decided on node types, never on strings."""
import pytest

from app.semantic.model import DefinitionError
from app.semantic.validate import check_name, validate_filters, validate_grains, validate_measure

COLS = ["amount", "status", "channel", "ordered_at"]


@pytest.mark.parametrize("text", [
    "SUM(amount)", "COUNT(*)", "COUNT(DISTINCT channel)", "AVG(CAST(amount AS DOUBLE))",
    "SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END)", "MAX(COALESCE(amount, 0) * 2)",
])
def test_accepted_measures(text):
    validate_measure(text, COLS, "athena")


@pytest.mark.parametrize("text,needle", [
    ("SUM(amount) OVER ()", "one aggregate"),
    ("SUM((SELECT 1))", "SUBQUERY"),
    ("SUM(SUM(amount))", "Nested"),
    ("APPROX_DISTINCT(amount)", "one aggregate"),
    ("amount", "one aggregate"),
    ("SUM(amount); DROP TABLE x", "no ';'"),
    ("SUM(o.amount)", "bare column"),
    ("SUM(nope)", "Unknown column"),
    ("SUM(*)", "COUNT(*)"),
    ("", "Required"),
])
def test_refused_measures(text, needle):
    with pytest.raises(DefinitionError) as e:
        validate_measure(text, COLS, "athena")
    assert e.value.field == "measure"
    assert needle in str(e.value)


def test_column_match_ignores_case():
    validate_measure("SUM(Amount)", COLS, "athena")


@pytest.mark.parametrize("text", [
    "status = 'paid'", "status = 'paid' AND amount > 0", "channel IN ('web', 'app')",
    "amount BETWEEN 1 AND 10", "channel IS NOT NULL", "channel LIKE 'w%'", "NOT status = 'void'",
])
def test_accepted_filters(text):
    assert validate_filters(text, COLS, "athena") is not None


@pytest.mark.parametrize("text,needle", [
    ("SUM(amount) > 0", "SUM"),
    ("amount", "condition"),
    ("status IN (SELECT 1)", "SUBQUERY"),
    ("nope = 1", "Unknown column"),
])
def test_refused_filters(text, needle):
    with pytest.raises(DefinitionError) as e:
        validate_filters(text, COLS, "athena")
    assert e.value.field == "filters" and needle in str(e.value)


def test_empty_filters_mean_none():
    assert validate_filters("  ", COLS, "athena") is None
    assert validate_filters(None, COLS, "athena") is None


@pytest.mark.parametrize("name", ["revenue", "a", "order_count_2"])
def test_good_names(name):
    assert check_name(name) == name


@pytest.mark.parametrize("name", ["Revenue", "1x", "_x", "a-b", "a" * 64, ""])
def test_bad_names(name):
    with pytest.raises(DefinitionError):
        check_name(name)


def test_grains_are_deduplicated_and_checked():
    assert validate_grains(["month", "day", "month"]) == ("month", "day")
    with pytest.raises(DefinitionError):
        validate_grains(["hour"])


@pytest.mark.parametrize("text", ["SUM(amount) = 'x", "SUM(amount) WHERE \"x"])
def test_untokenisable_measure_is_a_definition_error(text):
    """An unterminated quote raises TokenError, not ParseError: still a 422, never a 500."""
    with pytest.raises(DefinitionError) as e:
        validate_measure(text, COLS, "athena")
    assert e.value.field == "measure"


def test_untokenisable_filter_is_a_definition_error():
    with pytest.raises(DefinitionError) as e:
        validate_filters("status = 'paid", COLS, "athena")
    assert e.value.field == "filters"
