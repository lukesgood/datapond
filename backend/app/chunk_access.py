"""Which chunks of a collection a caller may retrieve.

The collection ACL decides whether a caller may search a collection at all. Inside
it, every chunk was equally visible: an HR collection shared with two departments
returned each department's documents to the other. This module is the rule that
narrows a search to the chunks a caller's attributes match.

A collection's rule is one line — "a chunk's `metadata[metadata_key]` must be one of
the caller's `attributes[user_attribute]` values" — using the same `users.attributes`
the table RLS engine already reads (`app/rls/loader.py`). The label gets onto the
chunk at ingest: an Iceberg source names a `label_column`, any source can carry
constant `labels`, and pasted documents carry their own metadata.

Fail closed in both directions that matter:
  - a chunk without the key is not visible, so a document ingested before labels
    existed does not leak into every department's results once the rule is on;
  - a caller without the attribute sees nothing, rather than everything.

Admins are held to it too, the same as `RLS_ADMIN_BYPASS=false` for tables: the
point is that retrieval returns what the caller is entitled to, and "admin" is a
role for managing the product, not a clearance.

The filter runs in SQL, in the WHERE of the vector query, so it applies before the
LIMIT: a caller gets their top-k from the chunks they may see, not a top-k with the
invisible ones removed afterwards.
"""
import json
import re
from dataclasses import dataclass
from typing import Any, List, Optional

_IDENT = re.compile(r"^[A-Za-z0-9_]{1,64}$")

# Keys ingest already writes. A label may not overwrite them: `row` or `key` standing
# in for a department would make a citation point at the wrong place.
RESERVED_METADATA_KEYS = frozenset({"schema", "table", "row", "bucket", "key"})


@dataclass(frozen=True)
class ChunkRule:
    metadata_key: str
    user_attribute: str


class InvalidRule(ValueError):
    pass


def valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENT.match(value))


def validate(raw: Any) -> ChunkRule:
    """A rule from an API body. Raises InvalidRule with a sentence a person can act on."""
    if not isinstance(raw, dict):
        raise InvalidRule("chunk access must be an object with metadata_key and user_attribute.")
    key, attr = raw.get("metadata_key"), raw.get("user_attribute")
    if not valid_identifier(key) or not valid_identifier(attr):
        raise InvalidRule("metadata_key and user_attribute must be 1-64 letters, digits "
                          "or underscores.")
    return ChunkRule(metadata_key=key, user_attribute=attr)


# A stored rule that no longer parses must not switch filtering off. Its key cannot
# appear in any chunk's metadata, so it matches nothing.
_DENY_ALL = ChunkRule(metadata_key="__invalid_chunk_rule__", user_attribute="__none__")


def parse_stored(raw: Any) -> Optional[ChunkRule]:
    """The collection's rule, or None when it has none. A malformed rule denies all."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return _DENY_ALL
    if raw is None or raw == {}:
        return None
    try:
        return validate(raw)
    except InvalidRule:
        return _DENY_ALL


def caller_values(attributes: Any, name: str) -> List[str]:
    """The caller's values for one attribute, as strings. Empty means none.

    An attribute is a string for most users and a list for someone who belongs to
    several departments; numbers and booleans compare as their text, which is how
    `metadata->>key` reads them too.
    """
    if isinstance(attributes, str):
        try:
            attributes = json.loads(attributes)
        except ValueError:
            return []
    if not isinstance(attributes, dict):
        return []
    value = attributes.get(name)
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        if item is None or isinstance(item, (dict, list)):
            continue
        text = str(item).lower() if isinstance(item, bool) else str(item)
        if text != "":
            out.append(text)
    return out


def validate_labels(labels: Any) -> dict:
    """Constant labels for every document of a source. Keys are identifiers, values
    short strings, and the keys ingest writes itself cannot be overridden."""
    if labels is None:
        return {}
    if not isinstance(labels, dict):
        raise InvalidRule("labels must be an object of key: value.")
    out = {}
    for key, value in labels.items():
        if not valid_identifier(key):
            raise InvalidRule(f"label key {key!r} must be 1-64 letters, digits or underscores.")
        if key in RESERVED_METADATA_KEYS:
            raise InvalidRule(f"label key {key!r} is written by ingest and cannot be a label.")
        if not isinstance(value, (str, int, float, bool)) or len(str(value)) > 256:
            raise InvalidRule(f"label {key!r} must be a string of at most 256 characters.")
        out[key] = value
    return out
