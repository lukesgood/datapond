"""Metric version + request -> one SQL statement. Deterministic, no I/O.

Built as a sqlglot tree and rendered in the engine dialect. Caller input reaches the
tree only as a registered dimension name (looked up, never spliced) or as a literal.
The measure and filters were validated when the version was saved (validate.py);
they are parsed again here to re-point their columns at the base alias, and held to the
same node allow-list on the way (defence in depth against a row that bypassed it).
"""
import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from sqlglot import exp

from app.semantic.model import Join, MetricInputError, MetricVersion
from app.semantic.periods import resolve_period
from app.semantic.validate import checked_stored

BASE = "b"
OPS = ("=", "!=", "in", ">", "<", "between")
MAX_LIMIT = 1000
_CMP = {"=": exp.EQ, "!=": exp.NEQ, ">": exp.GT, "<": exp.LT}


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    citation: dict


def _table(catalog: str, dotted: str, alias: str) -> exp.Table:
    schema, name = dotted.split(".", 1)
    return exp.Table(this=exp.to_identifier(name), db=exp.to_identifier(schema),
                     catalog=exp.to_identifier(catalog),
                     alias=exp.TableAlias(this=exp.to_identifier(alias)))


def _on_base(field: str, text: str, dialect: str) -> exp.Expression:
    tree = checked_stored(field, text, dialect)
    for col in tree.find_all(exp.Column):
        col.set("table", exp.to_identifier(BASE))
    return tree


def _literal(value) -> exp.Expression:
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise MetricInputError("where values must be finite numbers.")
        return exp.Literal.number(value)
    if isinstance(value, str):
        return exp.Literal.string(value)
    raise MetricInputError("where values must be strings, numbers or booleans.")


def _where_term(target: exp.Expression, op: str, value) -> exp.Expression:
    if op == "in":
        if not isinstance(value, list) or not value:
            raise MetricInputError("'in' needs a non-empty list.")
        return exp.In(this=target, expressions=[_literal(v) for v in value])
    if op == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise MetricInputError("'between' needs [low, high].")
        return exp.Between(this=target, low=_literal(value[0]), high=_literal(value[1]))
    cls = _CMP.get(op)
    if cls is None:
        raise MetricInputError(f"Unknown op {op!r}.", {"op": list(OPS)})
    return cls(this=target, expression=_literal(value))


def _ordering(order_by, outputs: List[str]) -> List[Tuple[int, bool]]:
    """[{field, desc?}] -> (1-based output position, desc). A field is an output column:
    the grain, a dimension in 'by', or the metric itself."""
    allowed = {"order_by": list(outputs)}
    if not isinstance(order_by, (list, tuple)):
        raise MetricInputError("'order_by' is a list of {field, desc}.", allowed)
    out: List[Tuple[int, bool]] = []
    for term in order_by:
        if (not isinstance(term, dict) or not set(term) <= {"field", "desc"}
                or not isinstance(term.get("field"), str)
                or not isinstance(term.get("desc", False), bool)):
            raise MetricInputError("Each order_by term is {field, desc}; field is a string, "
                                   "desc a boolean.", allowed)
        if term["field"] not in outputs:
            raise MetricInputError(f"Cannot order by {term['field']!r}: not in the result.",
                                   allowed)
        pos = outputs.index(term["field"]) + 1
        if any(p == pos for p, _ in out):
            raise MetricInputError(f"{term['field']!r} appears twice in 'order_by'.", allowed)
        out.append((pos, term.get("desc", False)))
    return out


def compile_metric(v: MetricVersion, *, engine_catalog: str, dialect: str, today: date,
                   by: Sequence[str] = (), period: Optional[str] = None,
                   grain: Optional[str] = None, where: Sequence[dict] = (),
                   order_by: Sequence[dict] = (), limit: Optional[int] = None) -> CompiledQuery:
    dims = [d.name for d in v.dimensions]
    # The MCP/REST schemas allow Any here; anything but a string is the caller's error,
    # answered with what is allowed, never a TypeError (500).
    if not isinstance(by, (list, tuple)) or not all(isinstance(n, str) for n in by):
        raise MetricInputError("'by' is a list of dimension names.", {"dimensions": dims})
    if grain is not None and not isinstance(grain, str):
        raise MetricInputError("grain is one of the metric's grains.", {"grains": list(v.grains)})
    if not isinstance(where or (), (list, tuple)):
        raise MetricInputError("'where' is a list of {dimension, op, value}.",
                               {"op": list(OPS), "dimensions": dims})
    for term in where or ():
        if (not isinstance(term, dict) or set(term) != {"dimension", "op", "value"}
                or not isinstance(term["dimension"], str) or not isinstance(term["op"], str)):
            raise MetricInputError("Each where term is {dimension, op, value}; dimension "
                                   "and op are strings.", {"op": list(OPS), "dimensions": dims})
    joins: Dict[str, Tuple[str, Join]] = {}       # to_table -> (alias, join); first use wins

    def target_of(name: str) -> exp.Expression:
        d = v.dimension(name)
        if d is None:
            raise MetricInputError(f"Unknown dimension {name!r}.", {"dimensions": dims})
        if d.join is None:
            return exp.column(d.column, table=BASE)
        alias = joins.setdefault(d.join.to_table, (f"j{len(joins) + 1}", d.join))[0]
        return exp.column(d.column, table=alias)

    select: List[exp.Expression] = []
    if grain is not None:
        if v.time_column is None or grain not in v.grains:
            raise MetricInputError(f"Unknown grain {grain!r}.", {"grains": list(v.grains)})
        select.append(exp.Anonymous(this="DATE_TRUNC", expressions=[
            exp.Literal.string(grain), exp.column(v.time_column, table=BASE)]).as_(grain))
    if len(set(by)) != len(by):
        raise MetricInputError("A dimension appears twice in 'by'.", {"dimensions": dims})
    for name in by:
        select.append(target_of(name).as_(name))
    select.append(_on_base("measure", v.measure, dialect).as_(v.metric))

    conds: List[exp.Expression] = []
    if v.filters:
        conds.append(exp.Paren(this=_on_base("filters", v.filters, dialect)))
    start = end = None
    if v.time_column is not None:
        if period is None:
            raise MetricInputError("period is required for this metric.",
                                   {"max_period_days": v.max_period_days})
        start, end = resolve_period(period, today)
        if (end - start).days > v.max_period_days:
            raise MetricInputError(f"period is longer than {v.max_period_days} days.",
                                   {"max_period_days": v.max_period_days})
        conds.append(exp.GTE(this=exp.column(v.time_column, table=BASE),
                             expression=exp.cast(exp.Literal.string(start.isoformat()), "DATE")))
        conds.append(exp.LT(this=exp.column(v.time_column, table=BASE),
                            expression=exp.cast(exp.Literal.string(end.isoformat()), "DATE")))
    elif period is not None:
        raise MetricInputError("This metric has no time column; omit period.")
    for term in where or ():
        conds.append(_where_term(target_of(term["dimension"]), term["op"], term["value"]))

    q = exp.select(*select).from_(_table(engine_catalog, v.base_table, BASE))
    for to_table, (alias, join) in joins.items():
        on = exp.and_(*[exp.EQ(this=exp.column(a, table=BASE), expression=exp.column(b, table=alias))
                        for a, b in join.on])
        q = q.join(_table(engine_catalog, to_table, alias), on=on, join_type="left")
    if conds:
        q = q.where(exp.and_(*conds))
    n_dims = len(select) - 1
    outputs = ([grain] if grain is not None else []) + list(by) + [v.metric]
    if n_dims:
        q = q.group_by(*[exp.Literal.number(i) for i in range(1, n_dims + 1)])
    # Requested order first, then every dimension ascending, so equal values (a tie at
    # the LIMIT boundary) always come back in the same order.
    requested = _ordering(order_by, outputs)
    tiebreak = [(i, False) for i in range(1, n_dims + 1) if i not in {p for p, _ in requested}]
    if requested or tiebreak:
        # Ascending stays a bare ordinal, so SQL for a query without order_by is unchanged.
        q = q.order_by(*[exp.Ordered(this=exp.Literal.number(p), desc=True) if d
                         else exp.Literal.number(p) for p, d in requested + tiebreak])
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            raise MetricInputError(f"limit is an integer from 1 to {MAX_LIMIT}.",
                                   {"limit": [1, MAX_LIMIT]})
        q = q.limit(limit)

    sql = q.sql(dialect=dialect, identify=True)
    return CompiledQuery(sql=sql, citation={
        "metric": v.metric, "version": v.version, "approved_by": v.approved_by,
        "approved_at": v.approved_at, "sql": sql,
        "period": [start.isoformat(), end.isoformat()] if start else None})
