"""Version + request -> SQL. Deterministic, dialect-aware, no caller text spliced in."""
from datetime import date

import pytest

from app.semantic.compile import compile_metric
from app.semantic.model import Dimension, Join, MetricInputError, MetricVersion

CUST = Join("sales.customers", (("customer_id", "id"),))
V = MetricVersion(
    metric="revenue", version=3, catalog="glue", base_table="sales.orders",
    measure="SUM(amount)", filters="status = 'paid'", time_column="ordered_at",
    grains=("month",), max_period_days=366,
    dimensions=(Dimension("channel", "channel"), Dimension("region", "region", CUST),
                Dimension("segment", "segment", CUST)),
    approved_by="root", approved_at="2026-10-15T00:00:00+00:00")
TODAY = date(2026, 10, 15)


def _c(**kw):
    kw.setdefault("period", "last_month")
    return compile_metric(V, engine_catalog="AwsDataCatalog", dialect="athena", today=TODAY, **kw)


def test_total_without_dimensions():
    assert _c().sql == (
        'SELECT SUM("b"."amount") AS "revenue" FROM "AwsDataCatalog"."sales"."orders" AS "b" '
        "WHERE (\"b\".\"status\" = 'paid') AND \"b\".\"ordered_at\" >= CAST('2026-09-01' AS DATE) "
        "AND \"b\".\"ordered_at\" < CAST('2026-10-01' AS DATE)")


def test_grain_join_and_dimensions():
    sql = _c(by=["region", "channel"], grain="month").sql
    assert sql.startswith('SELECT DATE_TRUNC(\'month\', "b"."ordered_at") AS "month", '
                          '"j1"."region" AS "region", "b"."channel" AS "channel", '
                          'SUM("b"."amount") AS "revenue"')
    assert 'LEFT JOIN "AwsDataCatalog"."sales"."customers" AS "j1" ON "b"."customer_id" = "j1"."id"' in sql
    assert sql.endswith("GROUP BY 1, 2, 3 ORDER BY 1, 2, 3")


def test_two_dimensions_share_one_join():
    sql = _c(by=["region", "segment"]).sql
    assert sql.count("LEFT JOIN") == 1
    assert '"j1"."segment"' in sql


def test_period_bounds_are_half_open():
    sql = _c().sql
    assert ">= CAST('2026-09-01' AS DATE)" in sql and "< CAST('2026-10-01' AS DATE)" in sql
    assert "<= CAST" not in sql


def test_trino_dialect_renders_too():
    sql = compile_metric(V, engine_catalog="iceberg", dialect="trino", today=TODAY,
                         period="last_month").sql
    assert 'FROM "iceberg"."sales"."orders" AS "b"' in sql


def test_same_input_same_sql():
    assert _c(by=["channel"]).sql == _c(by=["channel"]).sql


def test_where_values_stay_literals():
    sql = _c(where=[{"dimension": "channel", "op": "in", "value": ["web", "x' OR 1=1 --"]}]).sql
    assert "IN ('web', 'x'' OR 1=1 --')" in sql


@pytest.mark.parametrize("op,value,expected", [
    ("=", "web", "\"b\".\"channel\" = 'web'"),
    ("!=", "web", "\"b\".\"channel\" <> 'web'"),
    (">", 5, "\"b\".\"channel\" > 5"),
    ("between", [1, 2], "\"b\".\"channel\" BETWEEN 1 AND 2"),
])
def test_where_ops(op, value, expected):
    assert expected in _c(where=[{"dimension": "channel", "op": op, "value": value}]).sql


def test_citation_carries_version_and_period():
    c = _c().citation
    assert (c["metric"], c["version"], c["approved_by"]) == ("revenue", 3, "root")
    assert c["period"] == ["2026-09-01", "2026-10-01"] and c["sql"] == _c().sql


@pytest.mark.parametrize("kw,needle,allowed_key", [
    ({"by": ["country"]}, "Unknown dimension", "dimensions"),
    ({"grain": "day"}, "Unknown grain", "grains"),
    ({"period": None}, "period is required", "max_period_days"),
    ({"period": "2024-01-01..2026-01-01"}, "longer than", "max_period_days"),
    ({"where": [{"dimension": "channel", "op": "like", "value": "w%"}]}, "Unknown op", "op"),
])
def test_refusals_name_what_is_allowed(kw, needle, allowed_key):
    with pytest.raises(MetricInputError) as e:
        _c(**kw)
    assert needle in str(e.value) and allowed_key in e.value.allowed


@pytest.mark.parametrize("where", [
    [{"dimension": "channel", "op": "in", "value": []}],
    [{"dimension": "channel", "op": "between", "value": [1]}],
    [{"dimension": "channel", "op": "=", "value": {"x": 1}}],
    [{"dimension": "channel", "op": "="}],
])
def test_malformed_where_terms(where):
    with pytest.raises(MetricInputError):
        _c(where=where)


def test_duplicate_dimension_is_refused():
    with pytest.raises(MetricInputError):
        _c(by=["channel", "channel"])


def test_period_on_a_metric_without_time_column_is_refused():
    v = MetricVersion(metric="customers", version=1, catalog="glue",
                      base_table="sales.customers", measure="COUNT(*)")
    with pytest.raises(MetricInputError):
        compile_metric(v, engine_catalog="c", dialect="athena", today=TODAY, period="last_month")
    assert "WHERE" not in compile_metric(v, engine_catalog="c", dialect="athena", today=TODAY).sql


def test_rls_engine_rewrites_the_compiled_sql():
    from app.rls.engine import RlsPolicy, UserContext, enforce
    sql = _c(by=["region"]).sql
    pol = RlsPolicy(id="p1", catalog="awsdatacatalog", schema="sales", table="orders",
                    filter_expression="region = 'KR'", role_map={"business_analyst": False})
    r = enforce(sql, UserContext(user_id="u", username="ana", roles=["business_analyst"]),
                [pol], [], dialect="athena")
    assert r.applied_policy_ids == ["p1"]
    assert "WHERE (region = 'KR')) AS b" in r.sql


@pytest.mark.parametrize("term", [
    {"dimension": "channel", "op": ["in"], "value": ["web"]},
    {"dimension": "channel", "op": {"a": 1}, "value": "web"},
    {"dimension": 1, "op": "=", "value": "web"},
    {"dimension": ["channel"], "op": "=", "value": "web"},
])
def test_non_string_op_or_dimension_is_an_input_error(term):
    with pytest.raises(MetricInputError) as e:
        _c(where=[term])
    assert e.value.allowed


@pytest.mark.parametrize("by", [[["channel"]], [1], [{"x": 1}]])
def test_non_string_by_is_an_input_error(by):
    with pytest.raises(MetricInputError) as e:
        _c(by=by)
    assert e.value.allowed["dimensions"] == ["channel", "region", "segment"]


def test_non_string_grain_is_an_input_error():
    with pytest.raises(MetricInputError):
        _c(grain=["month"])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_refused(value):
    with pytest.raises(MetricInputError):
        _c(where=[{"dimension": "channel", "op": "=", "value": value}])
    with pytest.raises(MetricInputError):
        _c(where=[{"dimension": "channel", "op": "in", "value": [1, value]}])


@pytest.mark.parametrize("field,text", [
    ("measure", "SUM((SELECT 1))"),
    ("measure", "SUM(amount) OVER ()"),
    ("filters", "status IN (SELECT s FROM t)"),
])
def test_a_stored_definition_outside_the_allow_list_is_refused_at_compile(field, text):
    """Defence in depth: a row that reached the table without validate.py (a manual
    INSERT, an older rule) is a server-side data fault — ValueError, not caller input."""
    import dataclasses
    bad = dataclasses.replace(V, **{field: text})
    with pytest.raises(ValueError) as e:
        compile_metric(bad, engine_catalog="AwsDataCatalog", dialect="athena", today=TODAY,
                       period="last_month")
    assert not isinstance(e.value, MetricInputError)


def test_order_by_metric_desc_with_limit_breaks_ties_by_dimensions():
    sql = _c(by=["channel"], order_by=[{"field": "revenue", "desc": True}], limit=5).sql
    assert sql.endswith("GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5")


def test_order_by_dimension_ascending_keeps_other_dimensions_as_tiebreak():
    sql = _c(by=["region", "channel"], order_by=[{"field": "channel"}]).sql
    assert sql.endswith("GROUP BY 1, 2 ORDER BY 2, 1")


def test_order_by_grain():
    sql = _c(by=["channel"], grain="month", order_by=[{"field": "month", "desc": True}]).sql
    assert sql.endswith("GROUP BY 1, 2 ORDER BY 1 DESC, 2")


def test_limit_alone_keeps_default_order():
    assert _c(by=["channel"], limit=3).sql.endswith("GROUP BY 1 ORDER BY 1 LIMIT 3")


def test_order_and_limit_are_in_the_citation_sql():
    c = _c(by=["channel"], order_by=[{"field": "revenue", "desc": True}], limit=2)
    assert c.citation["sql"] == c.sql and "LIMIT 2" in c.sql


@pytest.mark.parametrize("order_by", [
    [{"field": "nope"}],                       # not an output column
    [{"field": "region"}],                     # a dimension not in 'by'
    [{"field": "channel"}, {"field": "channel"}],
    [{"field": "channel", "desc": "yes"}],
    [{"field": 1}],
    [{"column": "channel"}],
    "revenue",
])
def test_bad_order_by_is_an_input_error_naming_allowed_fields(order_by):
    with pytest.raises(MetricInputError) as e:
        _c(by=["channel"], order_by=order_by)
    assert e.value.allowed.get("order_by") == ["channel", "revenue"]


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 2.5, "5"])
def test_bad_limit_is_an_input_error(limit):
    with pytest.raises(MetricInputError) as e:
        _c(by=["channel"], limit=limit)
    assert e.value.allowed.get("limit") == [1, 1000]


@pytest.mark.parametrize("where", [5, {"dimension": "channel", "op": "=", "value": "web"}, "x"])
def test_non_list_where_is_an_input_error(where):
    with pytest.raises(MetricInputError) as e:
        _c(where=where)
    assert "op" in e.value.allowed
