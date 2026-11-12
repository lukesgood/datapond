"""Register one catalog's Iceberg tables in another catalog, through Trino.

This is the exit path off a provider catalog — AWS Glue to an Iceberg REST catalog such
as Polaris — without copying data. An Iceberg table's whole state lives in its metadata
files in object storage; a catalog only records where the current metadata file is.
Trino's `register_table` procedure writes that location into the target catalog, so the
same files answer from both catalogs. Nothing is moved and the source is not changed.

Statements issued (all through the in-cluster Trino):

    SHOW SCHEMAS FROM "<src>"
    SHOW TABLES FROM "<src>"."<schema>"
    SELECT file FROM "<src>"."<schema>"."<table>$metadata_log_entries" ORDER BY timestamp DESC LIMIT 1
    CREATE SCHEMA IF NOT EXISTS "<dst>"."<schema>"
    CALL "<dst>".system.register_table(schema_name => …, table_name => …,
                                       table_location => …, metadata_file_name => …)
    SELECT count(*) FROM "<cat>"."<schema>"."<table>"          (both sides, to verify)

Preconditions the caller owns: the target catalog must accept the table's location
(Polaris: the catalog's allowedLocations, `polaris.storage.extraAllowedLocations` in the
chart) and Trino must have `iceberg.register-table-procedure.enabled=true` on it (the
chart sets it on every Iceberg catalog it renders).
"""
import re
from dataclasses import dataclass, asdict
from typing import Iterable, List, Optional

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SKIP_SCHEMAS = {"information_schema", "system"}


def ident(name: str) -> str:
    """A bare identifier, double-quoted. Anything else is refused, not escaped."""
    if not _IDENT.match(str(name or "")):
        raise ValueError(f"Not an identifier: {name!r}")
    return f'"{name}"'


def sql_string(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def split_metadata_path(path: str):
    """(table location, metadata file name) from a metadata file path:
    s3://b/w/raw/t-1/metadata/00003-x.metadata.json → (s3://b/w/raw/t-1, 00003-x.metadata.json)."""
    head, sep, name = str(path).rpartition("/metadata/")
    if not sep or not name.endswith(".metadata.json") or "/" in name:
        raise ValueError(f"Not an Iceberg metadata file path: {path!r}")
    return head, name


@dataclass
class Item:
    schema: str
    table: str
    action: str                     # plan: register | exists | skip; apply: registered | mismatch | failed | exists | skip
    location: Optional[str] = None
    metadata_file: Optional[str] = None
    rows_source: Optional[int] = None
    rows_target: Optional[int] = None
    detail: Optional[str] = None

    def as_dict(self):
        return asdict(self)


def _names(cur, sql: str) -> List[str]:
    cur.execute(sql)
    return [r[0] for r in cur.fetchall()]


def plan(cur, src: str, dst: str, schema: Optional[str] = None,
         tables: Optional[Iterable[str]] = None) -> List[Item]:
    """What `apply` would do, without changing anything."""
    schemas = [schema] if schema else [s for s in _names(cur, f"SHOW SCHEMAS FROM {ident(src)}")
                                       if s not in _SKIP_SCHEMAS]
    wanted = set(tables) if tables else None
    out: List[Item] = []
    for s in schemas:
        present = set(_names(cur, f"SHOW TABLES FROM {ident(dst)}.{ident(s)}")) \
            if s in _names(cur, f"SHOW SCHEMAS FROM {ident(dst)}") else set()
        for t in _names(cur, f"SHOW TABLES FROM {ident(src)}.{ident(s)}"):
            if wanted is not None and t not in wanted:
                continue
            if t in present:
                out.append(Item(s, t, "exists", detail=f"{dst}.{s}.{t} already exists"))
                continue
            try:
                cur.execute(f'SELECT file FROM {ident(src)}.{ident(s)}."{t}$metadata_log_entries" '
                            "ORDER BY timestamp DESC LIMIT 1")
                row = cur.fetchone()
                location, meta = split_metadata_path(row[0])
            except Exception as e:      # a view, a non-Iceberg table, an unreadable one
                out.append(Item(s, t, "skip", detail=str(e)[:300]))
                continue
            out.append(Item(s, t, "register", location=location, metadata_file=meta))
    return out


def _count(cur, cat: str, schema: str, table: str) -> int:
    cur.execute(f"SELECT count(*) FROM {ident(cat)}.{ident(schema)}.{ident(table)}")
    return int(cur.fetchone()[0])


def apply(cur, items: List[Item], src: str, dst: str) -> List[Item]:
    """Register every planned table, then compare row counts. A refusal or a mismatch is
    reported on its row; the others go on."""
    out: List[Item] = []
    made_schemas = set()
    for it in items:
        if it.action != "register":
            out.append(it)
            continue
        try:
            if it.schema not in made_schemas:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {ident(dst)}.{ident(it.schema)}")
                made_schemas.add(it.schema)
            cur.execute(
                f"CALL {ident(dst)}.system.register_table("
                f"schema_name => {sql_string(it.schema)}, table_name => {sql_string(it.table)}, "
                f"table_location => {sql_string(it.location)}, "
                f"metadata_file_name => {sql_string(it.metadata_file)})")
            cur.fetchall()
            a, b = _count(cur, src, it.schema, it.table), _count(cur, dst, it.schema, it.table)
        except Exception as e:
            out.append(Item(**{**it.as_dict(), "action": "failed", "detail": str(e)[:500]}))
            continue
        action = "registered" if a == b else "mismatch"
        detail = None if a == b else f"row counts differ: {src} {a}, {dst} {b}"
        out.append(Item(**{**it.as_dict(), "action": action, "rows_source": a,
                           "rows_target": b, "detail": detail}))
    return out


def _cursor():
    from app.api.trino_util import trino_conn
    return trino_conn(timeout=600).cursor()
