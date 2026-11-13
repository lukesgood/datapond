"""Every auth_audit_log event type the code writes exists in the audit_event_type enum.

The audit insert is best-effort, so an unknown value fails silently: catalog_exported,
sync_target_recreated and catalog_mirror_diverged (2.6–2.7) were never recorded until
this was caught on the live node (2026-11-13). Scans the source for the literals rather
than trusting a list someone remembers to update."""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _enum_values():
    sql = "\n".join(p.read_text() for p in sorted((BACKEND / "migrations/versions").glob("*.sql")))
    base = re.search(r"CREATE TYPE public\.audit_event_type AS ENUM \((.*?)\);", sql, re.S).group(1)
    vals = set(re.findall(r"'([a-z_]+)'", base))
    vals |= set(re.findall(r"ALTER TYPE public\.audit_event_type ADD VALUE (?:IF NOT EXISTS )?'([a-z_]+)'", sql))
    return vals


def _written_types():
    found = set()
    for p in (BACKEND / "app").rglob("*.py"):
        text = p.read_text()
        # literal first value in an INSERT INTO auth_audit_log ... VALUES ('x', ...)
        for m in re.finditer(r"INSERT INTO auth_audit_log.{0,400}?VALUES\s*\(\s*'([a-z_]+)'", text, re.S):
            found.add((p.name, m.group(1)))
        # event names passed to an audit helper or to the INSERT as the first parameter
        for m in re.finditer(r"\"((?:catalog|sync|mirror|connector|source)_[a-z_]+)\"", text):
            if "audit" in text[max(0, m.start() - 400):m.end() + 200]:
                found.add((p.name, m.group(1)))
    return found


def test_every_audit_event_type_the_code_writes_is_in_the_enum():
    enum = _enum_values()
    missing = sorted({(f, t) for f, t in _written_types() if t not in enum
                      and not t.endswith(("_id", "_type", "_ids", "_table", "_tables", "_name", "_catalog"))})
    assert not missing, f"audit event types not in audit_event_type (add a migration): {missing}"
