"""Which tables RLS actually governs.

`RLS_DEFAULT_DENY` is off by default: a table with no policy passes through
unfiltered. That default is deliberate — flipping it on a policy-empty database
would refuse every query — but it means the governed state and the ungoverned state
are indistinguishable from the outside. Enable RLS, watch nothing break, conclude
the data is protected.

This module produces the readout that tells them apart, so turning default_deny on
is a decision made with the list in hand rather than a leap. Pure: it takes a table
list and a policy list and touches nothing.
"""
from typing import Iterable, List, Sequence, Tuple


def _key(catalog: str, schema: str, table: str) -> str:
    # Lower-cased to match the engine, which lower-cases identifiers before looking a
    # policy up. Comparing raw here would report a policy on `Orders` as covering
    # nothing.
    return f"{catalog}.{schema}.{table}".lower()


def coverage(tables: Sequence[Tuple[str, str, str]],
             policies: Iterable,
             masks: Iterable) -> dict:
    """Report RLS coverage over `tables`.

    `tables` is (catalog, schema, table) as the catalog reports them. `policies` and
    `masks` are anything with .catalog/.schema/.table — RlsPolicy and MaskPolicy both
    qualify.

    A masking policy counts as coverage on its own. Such a table is governed: every
    row comes back, but the sensitive columns do not. Reporting it as uncovered would
    send someone looking for a gap that is already closed.
    """
    known = {_key(c, s, t) for c, s, t in tables}
    protected = {_key(p.catalog, p.schema, p.table) for p in policies} | \
                {_key(m.catalog, m.schema, m.table) for m in masks}

    covered = sorted(known & protected)
    uncovered = sorted(known - protected)
    # A policy naming a table the catalog does not have protects nothing, while still
    # showing up in the policy list — a control everyone believes is on.
    orphaned = sorted(protected - known)

    return {
        "total": len(known),
        "covered": covered,
        "covered_count": len(covered),
        "uncovered": uncovered,
        "uncovered_count": len(uncovered),
        "orphaned_policies": orphaned,
        # Named for the question being asked rather than for the data: this is what
        # an operator wants before setting RLS_DEFAULT_DENY=true.
        "would_block_under_default_deny": uncovered,
    }


def rls_posture(rls_enabled: bool, default_deny: bool, uncovered: int) -> str:
    """The one-word (or one-phrase) answer to "is default-deny safe to flip yet",
    meant for `/health/ready`'s `state` dict beside `migrations` and `base_schema`.

    Three states, not two: "off" and "enforcing" are stable — nothing left to
    decide — but "advisory" always names the uncovered count, including zero.
    Zero uncovered is not the same claim as `default_deny=true`: it says every
    table *currently* has a policy, not that an unlisted one would be refused. The
    next table added without a policy would pass through here and be blocked
    there. Collapsing "advisory, 0 uncovered" into "enforcing" would erase that
    difference right when it matters least — because nothing is currently wrong.
    """
    if not rls_enabled:
        return "off"
    if default_deny:
        return "enforcing"
    return f"advisory ({uncovered} tables uncovered)"


def startup_warning(rls_enabled: bool, default_deny: bool,
                    uncovered: int) -> "str | None":
    """The one sentence worth logging at boot, or None when there is nothing to say.

    Only one combination is worth interrupting anyone over: RLS on, strict mode off,
    and tables with no policy. That is the state that looks like protection to
    whoever enabled it and is not.
    """
    if not rls_enabled or default_deny or uncovered <= 0:
        return None
    return (f"RLS is enabled but {uncovered} catalog table(s) have no policy, and "
            f"RLS_DEFAULT_DENY is off — queries against them are NOT filtered. "
            f"GET /api/governance/rls/coverage lists them. Set RLS_DEFAULT_DENY=true "
            f"to block unregistered tables instead.")
