"""Mask PII in a pandas chunk before it is written to Iceberg.

Used by the Python-engine connectors (REST, custom, S3) — the ones that still read rows
into the backend. Trino-backed sources mask in SQL instead (trino_sync / pii_ko.mask_sql).
"""


def _mask_pii_in_chunk(chunk, pii_columns) -> int:
    """Mask configured columns' string cells (pii_ko) BEFORE they're written to Iceberg —
    sensitive data never lands raw in the lakehouse. pii_columns == ['*'] scans all
    string columns; otherwise only the named ones. Returns # of cells changed. In-place."""
    if not pii_columns:
        return 0
    from app.guardrails import pii_ko
    cols = (list(chunk.columns) if pii_columns == ["*"]
            else [c for c in pii_columns if c in chunk.columns])
    changed = 0
    for col in cols:
        if chunk[col].dtype != object:   # only string/object columns can carry PII text
            continue

        def _m(v):
            nonlocal changed
            if isinstance(v, str) and v:
                mv = pii_ko.mask(v)
                if mv != v:
                    changed += 1
                return mv
            return v
        chunk[col] = chunk[col].map(_m)
    return changed


mask_pii_in_chunk = _mask_pii_in_chunk
