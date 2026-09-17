"""What a collection's sensitivity label means, in one place.

Access control, masking and egress were three mechanisms that could disagree. A
collection marked `block` for PII still had its text embedded by a cloud provider,
because masking was a property of the collection and egress was a property of the
deployment. An operator had to know all three and set them consistently by hand.

A label states what the data IS; the consequences are derived here:

    label          masking floor   may leave the deployment
    public         -               yes
    internal       -               yes
    confidential   mask            yes
    restricted     block           NO — local models only, whatever the deployment allows

Tightening only, always. A `public` label cannot loosen a deployment that masks or one
that is already local-only — the same rule pii_ko.strictest() follows, and for the same
reason: a per-row value that can weaken a deployment-wide guarantee is not a guarantee.
An unknown or NULL label derives nothing and leaves the deployment default in force.
"""
from typing import Optional

LABELS = ("public", "internal", "confidential", "restricted")

# label -> the weakest PII mode it will tolerate (None: says nothing about masking)
_PII_FLOOR = {
    "public": None,
    "internal": None,
    "confidential": "mask",
    "restricted": "block",
}

# Labels whose content must not reach an external provider, whatever AI_EGRESS_POLICY says.
_LOCAL_ONLY = frozenset({"restricted"})


def normalize(label: Optional[str]) -> Optional[str]:
    """A recognised label, or None. Unknown values are ignored rather than guessed at."""
    if not isinstance(label, str):
        return None
    value = label.strip().lower()
    return value if value in LABELS else None


def pii_floor(label: Optional[str]) -> Optional[str]:
    """The PII mode this label requires at minimum, for pii_ko.tighten()."""
    return _PII_FLOOR.get(normalize(label) or "", None)


def forces_local_only(label: Optional[str]) -> bool:
    """True when this label forbids sending content to an external model provider."""
    return (normalize(label) or "") in _LOCAL_ONLY
