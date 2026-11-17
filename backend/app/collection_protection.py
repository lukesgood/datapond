"""Who may change a collection's PII mode and sensitivity label — pure, no I/O.

Both columns already existed and were enforced on every request (pii_ko.tighten,
sensitivity.pii_floor / forces_local_only), but nothing could set them except SQL.

Raising protection is always allowed to anyone who may write the collection: it can
only make answers safer. Lowering it — block → mask, restricted → internal, a mode
back to "inherit" — decides what personal data reaches a model or leaves the
deployment, so it is a governance decision and needs `governance:write`, not just
ownership of the collection.
"""
from typing import Optional

from app import sensitivity

PII_MODES = ("off", "mask", "block")

# None (inherit) ranks lowest: the deployment default may be weaker than what was set.
_PII_RANK = {None: 0, "off": 1, "mask": 2, "block": 3}
_SENS_RANK = {None: 0, **{label: i + 1 for i, label in enumerate(sensitivity.LABELS)}}


def valid_pii_mode(v: object) -> bool:
    return v is None or v in PII_MODES


def valid_sensitivity(v: object) -> bool:
    return v is None or v in sensitivity.LABELS


def lowers_pii(old: Optional[str], new: Optional[str]) -> bool:
    return _PII_RANK.get(new, 0) < _PII_RANK.get(old, 0)


def lowers_sensitivity(old: Optional[str], new: Optional[str]) -> bool:
    return _SENS_RANK.get(new, 0) < _SENS_RANK.get(old, 0)
