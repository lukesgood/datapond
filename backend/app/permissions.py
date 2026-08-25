"""What each role may do — pure, dependency-free, like app/capabilities.py.

Five roles were seeded into the database from the start, but nothing outside the RLS
engine ever read them: the application layer enforced a single admin/not-admin split,
so a "viewer" could create and delete connectors and knowledge collections. This
module is the missing half of that model.

Two rules shape the matrix.

**Money is its own permission.** `ai:generate` covers every action that spends model
tokens. Per-user spend attribution is a governance claim this product makes, and an
unbounded ability to spend for anyone who can log in contradicts it. Splitting it out
is also what makes `viewer` and `business_analyst` different roles rather than two
names for the same thing.

**Writing is what gets withheld.** Reading stays broad. The change removes privileges
that were granted by accident, rather than fencing off the product — which also keeps
the upgrade from breaking every existing account's day-to-day use.

Capability flags and permissions are orthogonal and both must pass: a capability says
the deployment has the feature, a permission says this person may use it.
"""
from typing import Dict, FrozenSet, Optional

# ── Vocabulary ────────────────────────────────────────────────────────────────
# resource:action. Kept small and fixed — a permission nothing enforces is a lie.

ALL_PERMISSIONS: FrozenSet[str] = frozenset({
    "catalog:read",       # browse the catalog
    "query:run",          # execute SQL
    "dashboard:write",    # save and delete dashboards
    "knowledge:read",     # read collections and cited answers
    "knowledge:write",    # create, ingest into, and delete collections
    "ai:generate",        # anything that spends model tokens (Ask AI, RAG, embed)
    "connector:read",     # see sources and their sync state
    "connector:write",    # create, edit, delete, and run connectors
    "pipeline:write",     # transforms and streaming
    "workbench:read",     # browse notebooks and tracked experiments
    "workbench:write",    # run notebooks and mutate experiments
    "governance:read",    # RLS and masking policies, PII reports
    "governance:write",   # change those policies
    "audit:read",         # the audit log and stream
    "spend:read",         # model usage and cost reporting
    "settings:write",     # system settings, model providers
    "user:manage",        # accounts and role assignment
    "service:manage",     # infrastructure and storage operations
})

_READ_BASELINE = {"catalog:read", "knowledge:read"}

ROLE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    "admin": ALL_PERMISSIONS,

    # Brings data in. No model spend: ingestion is not a generative workload.
    "data_engineer": frozenset(_READ_BASELINE | {
        "query:run", "connector:read", "connector:write", "pipeline:write",
        "workbench:read", "workbench:write",
    }),

    # The product's stated target user — AI application teams — had no role at all.
    # Builds collections, spends on models, and can see what that spend cost.
    "ai_engineer": frozenset(_READ_BASELINE | {
        "query:run", "knowledge:write", "ai:generate", "connector:read", "spend:read",
        "workbench:read", "workbench:write",
    }),

    "data_scientist": frozenset(_READ_BASELINE | {
        "query:run", "knowledge:write", "ai:generate", "dashboard:write",
        "workbench:read", "workbench:write",
    }),

    "business_analyst": frozenset(_READ_BASELINE | {
        "query:run", "dashboard:write", "workbench:read",
    }),

    # Reviews the governance system and can verify it by running a query — checking
    # that a masking policy actually masks means selecting the column. Writes nothing.
    "auditor": frozenset(_READ_BASELINE | {
        "query:run", "governance:read", "audit:read", "spend:read",
        "workbench:read",
    }),

    "viewer": frozenset(_READ_BASELINE | {"query:run"}),
}

KNOWN_ROLES = tuple(ROLE_PERMISSIONS)

# Roles that may be assigned through the API. Same set — a role nobody can be given
# is as useless as one nothing enforces.
ASSIGNABLE_ROLES = KNOWN_ROLES


def _normalize(role: Optional[str]) -> str:
    return (role or "").strip().lower()


def permissions_for(role: Optional[str]) -> FrozenSet[str]:
    """Permissions held by `role`.

    An unrecognised role gets the viewer set rather than nothing. Fail-closed here
    means withholding writes, not locking out a deployment that carries a custom
    string in `users.role` — and `auth.py` already defaults a missing claim to
    'viewer', so this keeps one answer for the same question.
    """
    return ROLE_PERMISSIONS.get(_normalize(role), ROLE_PERMISSIONS["viewer"])


def has_permission(role: Optional[str], permission: str) -> bool:
    return permission in permissions_for(role)
