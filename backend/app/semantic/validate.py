"""What a metric definition may contain, decided on the parsed tree.

Strings are never searched for keywords: `SUM(amount)` and `SUM((SELECT …))` differ
only in their node types, so node types are what is checked. Anything not on an
allow-list is refused — a node type sqlglot adds later is refused until someone adds
it here.
"""
import re
from typing import Iterable, Optional

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.semantic.model import GRAINS, DefinitionError

NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
AGGREGATES = (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)

_SCALAR = (exp.Column, exp.Identifier, exp.Literal, exp.Null, exp.Boolean, exp.Paren,
           exp.Neg, exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Cast, exp.DataType,
           exp.Coalesce, exp.Case, exp.If)
_PREDICATE = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.In, exp.Between,
              exp.Is, exp.Like, exp.And, exp.Or, exp.Not)

MEASURE_NODES = _SCALAR + _PREDICATE + AGGREGATES + (exp.Distinct, exp.Star)
FILTER_NODES = _SCALAR + _PREDICATE


def check_name(name: str) -> str:
    if not isinstance(name, str) or not NAME.match(name):
        raise DefinitionError("name", "Use lowercase letters, digits and _; start with a "
                                      "letter; at most 63 characters.")
    return name


def _parse_one(field: str, text: Optional[str], dialect: str) -> exp.Expression:
    if not isinstance(text, str) or not text.strip():
        raise DefinitionError(field, "Required.")
    try:
        trees = [t for t in sqlglot.parse(text, dialect=dialect) if t is not None]
    except SqlglotError as e:        # ParseError, and TokenError for an unterminated quote
        raise DefinitionError(field, f"Not a valid expression: {str(e).splitlines()[0][:200]}")
    if len(trees) != 1:
        raise DefinitionError(field, "Exactly one expression; no ';'.")
    return trees[0]


def _check_nodes(field: str, tree: exp.Expression, allowed: tuple,
                 columns: Optional[set]) -> None:
    """`columns` None checks node types only (the stored-definition re-check)."""
    for node in tree.walk():
        if not isinstance(node, allowed):
            raise DefinitionError(field, f"{node.key.upper()} is not allowed here.")
        if isinstance(node, exp.Column) and columns is not None:
            if node.table:
                raise DefinitionError(field, f"Use bare column names of the base table, not {node.sql()}.")
            if node.name.lower() not in columns:
                raise DefinitionError(field, f"Unknown column {node.name!r} on the base table.")
        if isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count):
            raise DefinitionError(field, "* is allowed only as COUNT(*).")


def validate_measure(text: str, columns: Iterable[str], dialect: str) -> exp.Expression:
    cols = {c.lower() for c in columns}
    tree = _parse_one("measure", text, dialect)
    if not isinstance(tree, AGGREGATES):
        raise DefinitionError("measure", "Must be one aggregate: SUM, COUNT, AVG, MIN or MAX.")
    _check_nodes("measure", tree, MEASURE_NODES, cols)
    if sum(1 for n in tree.walk() if isinstance(n, AGGREGATES)) != 1:
        raise DefinitionError("measure", "Nested aggregates are not allowed.")
    return tree


def validate_filters(text: Optional[str], columns: Iterable[str],
                     dialect: str) -> Optional[exp.Expression]:
    if text is None or not str(text).strip():
        return None
    cols = {c.lower() for c in columns}
    tree = _parse_one("filters", text, dialect)
    _check_nodes("filters", tree, FILTER_NODES, cols)
    if not isinstance(tree, _PREDICATE):
        raise DefinitionError("filters", "Must be a condition, e.g. status = 'paid'.")
    return tree


def checked_stored(field: str, text: str, dialect: str) -> exp.Expression:
    """A stored measure or filter, parsed and held to the same node allow-list before it
    is compiled. It passed validate_measure/validate_filters when saved; failing here
    means the row did not come through them (a manual INSERT, an older rule) — a
    server-side data fault, so a plain ValueError rather than a caller's 400."""
    try:
        tree = _parse_one(field, text, dialect)
        if field == "measure" and not isinstance(tree, AGGREGATES):
            raise DefinitionError(field, "Must be one aggregate.")
        _check_nodes(field, tree, MEASURE_NODES if field == "measure" else FILTER_NODES, None)
        if field == "measure" and sum(1 for n in tree.walk() if isinstance(n, AGGREGATES)) != 1:
            raise DefinitionError(field, "Nested aggregates are not allowed.")
        if field != "measure" and not isinstance(tree, _PREDICATE):
            raise DefinitionError(field, "Must be a condition.")
    except DefinitionError as e:
        raise ValueError(f"Stored {field} is not a valid definition: {e}") from None
    return tree


def validate_grains(grains: Iterable[str]) -> tuple:
    out = tuple(dict.fromkeys(grains or ()))
    bad = [g for g in out if g not in GRAINS]
    if bad:
        raise DefinitionError("grains", f"Unknown grain(s) {bad}; use {list(GRAINS)}.")
    return out
