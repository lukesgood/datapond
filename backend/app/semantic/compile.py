"""Metric version + request -> one SQL statement. Deterministic, no I/O.

Built as a sqlglot tree and rendered in the engine dialect. Caller input reaches the
tree only as a registered dimension name (looked up, never spliced) or as a literal.
The measure and filters were validated when the version was saved (validate.py);
they are parsed again here only to re-point their columns at the base alias.
"""
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

import sqlglot
from sqlglot import exp

from app.semantic.model import Join, MetricInputError, MetricVersion
from app.semantic.periods import resolve_period

BASE = "b"
OPS = ("=", "!=", "in", ">", "<", "between")
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


def _on_base(text: str, dialect: str) -> exp.Expression:
    tree = sqlglot.parse_one(text, dialect=dialect)
    for col in tree.find_all(exp.Column):
        col.set("table", exp.to_identifier(BASE))
    return tree


def _literal(value) -> exp.Expression:
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
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


def compile_metric(v: MetricVersion, *, engine_catalog: str, dialect: str, today: date,
                   by: Sequence[str] = (), period: Optional[str] = None,
                   grain: Optional[str] = None, where: Sequence[dict] = ()) -> CompiledQuery:
    dims = [d.name for d in v.dimensions]
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
    select.append(_on_base(v.measure, dialect).as_(v.metric))

    conds: List[exp.Expression] = []
    if v.filters:
        conds.append(exp.Paren(this=_on_base(v.filters, dialect)))
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
        if not isinstance(term, dict) or set(term) != {"dimension", "op", "value"}:
            raise MetricInputError("Each where term is {dimension, op, value}.",
                                   {"op": list(OPS), "dimensions": dims})
        conds.append(_where_term(target_of(term["dimension"]), term["op"], term["value"]))

    q = exp.select(*select).from_(_table(engine_catalog, v.base_table, BASE))
    for to_table, (alias, join) in joins.items():
        on = exp.and_(*[exp.EQ(this=exp.column(a, table=BASE), expression=exp.column(b, table=alias))
                        for a, b in join.on])
        q = q.join(_table(engine_catalog, to_table, alias), on=on, join_type="left")
    if conds:
        q = q.where(exp.and_(*conds))
    n_dims = len(select) - 1
    if n_dims:
        q = q.group_by(*[exp.Literal.number(i) for i in range(1, n_dims + 1)])
        q = q.order_by(*[exp.Literal.number(i) for i in range(1, n_dims + 1)])

    sql = q.sql(dialect=dialect, identify=True)
    return CompiledQuery(sql=sql, citation={
        "metric": v.metric, "version": v.version, "approved_by": v.approved_by,
        "approved_at": v.approved_at, "sql": sql,
        "period": [start.isoformat(), end.isoformat()] if start else None})
