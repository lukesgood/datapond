"""Whether this pod should receive traffic.

Both Kubernetes probes pointed at `/health`, which returned `{"status": "healthy"}`
unconditionally. That answers "is the process running" — a liveness question — and
was being used to answer "can this pod serve requests", which is not the same thing.

It matters here more than it would elsewhere. Every schema bootstrap in this
application runs at startup, catches its own exception and logs a warning, so a
backend can reach Ready with tables missing and fail requests one endpoint at a
time. Until there are versioned migrations that stop the release, the least this can
do is refuse traffic when the schema it needs is not there.

The decision is a plain object with no pool and no HTTP, so the policy is testable
without a database.
"""
import threading
from typing import Dict, FrozenSet, List, Optional, Set


class Readiness:
    """Records bootstrap outcomes and answers whether the pod is ready.

    Required names hold the pod back; anything else is advisory. Add-on schemas
    belong to features a deployment may not have enabled, and blocking on them would
    turn every optional component into a mandatory one.
    """

    def __init__(self, required: Set[str]):
        self._required: FrozenSet[str] = frozenset(required)
        self._lock = threading.Lock()
        self._ok: Set[str] = set()
        self._failed: Dict[str, str] = {}

    def record(self, name: str, ok: bool, detail: Optional[str] = None) -> None:
        """Report how a bootstrap went. Later calls win, so a retry can clear a
        failure — several of these bootstraps already retry against a database that
        is not up yet."""
        with self._lock:
            if ok:
                self._ok.add(name)
                self._failed.pop(name, None)
            else:
                self._ok.discard(name)
                self._failed[name] = detail or "failed"

    def status(self) -> dict:
        with self._lock:
            failed = sorted(n for n in self._failed if n in self._required)
            pending = sorted(self._required - self._ok - set(self._failed))
            return {
                # Not ready until every required bootstrap has actually reported
                # success. Starting from ready would serve traffic during precisely
                # the window this exists to cover.
                "ready": not failed and not pending,
                "failed": failed,
                "pending": pending,
                "detail": dict(self._failed),
            }


# Bootstraps without which the product cannot answer a request correctly. Optional
# add-on schemas are deliberately absent.
REQUIRED = {"base_schema"}

readiness = Readiness(required=REQUIRED)
