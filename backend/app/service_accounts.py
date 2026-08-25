"""API-key credentials for non-human callers — pure, no I/O.

An AI app or agent had no identity of its own. It had to carry a person's JWT, which
expires in a day, cannot be revoked without disabling that person, grants everything
that person can do, and points spend attribution and the audit log at the wrong
actor — in a product whose differentiator is per-user spend attribution.

A service account is a `users` row with `auth_method='service'`, not a parallel
entity. Everything downstream already keys off `users(id)`: the audit log, query
history, role assignment, collection ownership, RLS user context, and the LiteLLM
`user` field that spend reporting groups by. A separate table would mean duplicating
all of it. So this module is only the credential — the identity is a user.

Storage shape comes from `api_keys` in schema/auth.sql, which was designed for this
and never implemented: `key_prefix` for display, `key_hash` for verification,
`scopes` to narrow a key below its account.
"""
import hashlib
import hmac
import secrets
from typing import FrozenSet, Optional, Sequence, Set, Tuple

from app.permissions import permissions_for

KEY_PREFIX = "dp_sk_"
_ENTROPY_BYTES = 32
# api_keys.key_prefix is VARCHAR(16); keep room for the marker plus a few characters
# so a key is identifiable in a list without any of it being guessable.
_STORED_PREFIX_LEN = 14

# A credential that lives in a config file or an environment variable must not be able
# to reshape the deployment, no matter which role its account holds. These are the
# actions that require a person who logged in.
NEVER_FOR_SERVICE_ACCOUNTS: FrozenSet[str] = frozenset({
    "user:manage",
    "settings:write",
})


def generate_key() -> Tuple[str, str, str]:
    """Return (plaintext, stored_prefix, sha256_hex).

    The plaintext is shown once, at creation, and never stored.
    """
    key = KEY_PREFIX + secrets.token_urlsafe(_ENTROPY_BYTES)
    return key, key[:_STORED_PREFIX_LEN], hash_key(key)


def hash_key(key: str) -> str:
    """SHA-256 of the key.

    Deliberately not bcrypt. A password is low-entropy and chosen by a human, so it
    needs a slow KDF; this is 256 bits of CSPRNG output, where a dictionary attack has
    nothing to work with. Bcrypt here would only add its cost to *every authenticated
    request*, since a key is verified on each one rather than at login.
    """
    return hashlib.sha256((key or "").encode()).hexdigest()


def key_matches(key: str, stored_hash: str) -> bool:
    """Constant-time comparison, so a timing signal cannot walk the hash."""
    return hmac.compare_digest(hash_key(key), stored_hash or "")


def looks_like_api_key(token: Optional[str]) -> bool:
    """Whether a bearer token is one of ours rather than a JWT.

    Lets one Authorization header carry either credential without the client having to
    know which scheme the server wants.
    """
    return bool(token) and token.startswith(KEY_PREFIX)


def effective_permissions(role: Optional[str], scopes: Sequence[str]) -> Set[str]:
    """What a key may do: its account's role, narrowed by `scopes`, never widened.

    Scopes are intersected rather than trusted — a scope naming a permission the
    account does not hold grants nothing, so a stale or hand-edited row cannot
    escalate. The administrative set is withheld regardless of role.
    """
    granted = set(permissions_for(role)) - set(NEVER_FOR_SERVICE_ACCOUNTS)
    requested = {s.strip() for s in (scopes or []) if s and s.strip()}
    if requested:
        granted &= requested
    return granted
