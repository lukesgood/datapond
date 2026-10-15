"""Metric definitions as the compiler sees them. No I/O."""
from dataclasses import dataclass
from typing import Optional, Tuple

GRAINS: Tuple[str, ...] = ("day", "week", "month", "quarter", "year")


class DefinitionError(ValueError):
    """A definition that cannot be saved. `field` names the input at fault (422)."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


class MetricInputError(ValueError):
    """A query the definition does not allow (400). `allowed` lets an agent correct
    itself without a second describe call."""

    def __init__(self, message: str, allowed: Optional[dict] = None):
        super().__init__(message)
        self.allowed = allowed or {}


@dataclass(frozen=True)
class Join:
    to_table: str                              # "schema.table", same catalog
    on: Tuple[Tuple[str, str], ...]            # (base column, target column) pairs


@dataclass(frozen=True)
class Dimension:
    name: str
    column: str
    join: Optional[Join] = None


@dataclass(frozen=True)
class MetricVersion:
    metric: str
    version: int
    catalog: str                               # registry name
    base_table: str                            # "schema.table"
    measure: str
    filters: Optional[str] = None
    time_column: Optional[str] = None
    grains: Tuple[str, ...] = ()
    max_period_days: int = 366
    dimensions: Tuple[Dimension, ...] = ()
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    created_by: Optional[str] = None           # user id, for the draft-preview rule

    def dimension(self, name: str) -> Optional[Dimension]:
        return next((d for d in self.dimensions if d.name == name), None)
