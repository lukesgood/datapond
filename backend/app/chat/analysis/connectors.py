"""Reads over sources: what is connected, what ran, and what the checks found."""
from typing import Callable, Dict

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class ConnectionRef(_Strict):
    connection_id: str


class ConnectionHistory(_Strict):
    connection_id: str
    # Bounded: the model puts whatever comes back into a prompt, and an unbounded
    # history is an unbounded prompt.
    limit: int = Field(default=20, ge=1, le=100)


async def list_sources(params: dict, user: dict) -> dict:
    from app.api.connectors import list_connections
    return {"sources": await list_connections(user=user)}


async def sync_history(params: dict, user: dict) -> dict:
    from app.api.connectors import get_sync_history
    return {"history": await get_sync_history(
        connection_id=params["connection_id"], limit=params["limit"], user=user)}


async def quality_checks(params: dict, user: dict) -> dict:
    from app.api.connectors import get_quality_checks
    return {"quality": await get_quality_checks(
        connection_id=params["connection_id"], limit=params["limit"], user=user)}


_RECENT_RUNS = 10


async def diagnose_sync(params: dict, user: dict) -> dict:
    """Why did this source's last sync go the way it did?

    History and quality checks read together, because the answer is often in the one
    the person was not looking at: a run that ends 'success' having loaded a tenth of
    the usual rows is a failure that does not announce itself.
    """
    from app.api.connectors import get_quality_checks, get_sync_history
    from app.chat.diagnosis import Diagnosis

    cid = params["connection_id"]
    history = await get_sync_history(connection_id=cid, limit=_RECENT_RUNS, user=user)
    quality = await get_quality_checks(connection_id=cid, limit=_RECENT_RUNS, user=user)

    # get_sync_history returns a plain list of sessions — no wrapper object.
    sessions = list(history or [])
    checks = (quality or {}).get("checks") or []

    d = Diagnosis(f"source {cid!r}")
    d.fact("runs_examined", len(sessions))
    d.fact("quality_checks_examined", len(checks))

    if not sessions:
        d.skipped("Outcome not checked: this source has no sync runs on record yet.")
    else:
        last = sessions[0]
        d.fact("last_status", last.get("status", ""))
        d.fact("last_started_at", str(last.get("started_at", "")))
        if str(last.get("status", "")).lower() not in ("success", "ok", "completed"):
            d.signal("bad", "The most recent sync did not succeed.",
                     status=last.get("status"), error=last.get("error_message"))
        else:
            d.signal("ok", "The most recent sync succeeded.",
                     status=last.get("status"))

        # duration_ms is milliseconds on the wire; convert once here so every
        # downstream comparison — and every evidence key — is genuinely in seconds.
        durations = [s.get("duration_ms") / 1000.0 for s in sessions
                     if isinstance(s.get("duration_ms"), (int, float))]
        if len(durations) >= 3:
            recent, earlier = durations[0], sum(durations[1:]) / len(durations[1:])
            # Twice the recent average, and not a rounding artefact on a fast sync.
            if earlier > 0 and recent > earlier * 2 and recent > 30:
                d.signal("warn", "The last run took markedly longer than the ones "
                                 "before it.",
                         last_seconds=round(recent, 1),
                         previous_average_seconds=round(earlier, 1))
        else:
            d.skipped("Duration trend not checked: fewer than three timed runs on "
                      "record.")

    def _status_word(c: dict) -> str:
        # overall_status is the primary field; row_change_status is the fallback
        # when a check row predates or omits it.
        return str(c.get("overall_status") or c.get("row_change_status") or "").strip().lower()

    tripped = []
    any_alert = False
    for c in checks:
        word = _status_word(c)
        if word == "ok":
            continue
        if word == "alert":
            any_alert = True
        # "warning", and any unrecognised or missing status word, is treated as a
        # check that tripped — never silently read as healthy.
        tripped.append(c)

    if not checks:
        d.skipped("Data quality not checked: no check results recorded for this "
                  "source.")
    elif tripped:
        worst = "bad" if any_alert else "warn"
        d.signal(worst, "Data quality checks flagged this source's recent loads.",
                 findings=tripped[:5])
    else:
        d.signal("ok", "Data quality checks passed on the recent loads.")

    return d.done()


ACTIONS = (
    Action("connectors.list_sources", "List sources",
           "Every connected source and its current sync state.",
           ("*",), "connector:read", ActionKind.READ, _Strict,
           capability="connectors"),
    Action("connectors.sync_history", "Sync history",
           "Recent sync runs for one source: when, how long, and how they ended.",
           ("*",), "connector:read", ActionKind.READ, ConnectionHistory,
           capability="connectors"),
    Action("connectors.quality_checks", "Quality checks",
           "Row-count drift and null-rate findings recorded after a source's syncs.",
           ("*",), "connector:read", ActionKind.READ, ConnectionHistory,
           capability="connectors"),
    Action("connectors.diagnose_sync", "Diagnose sync",
           "Why a source's syncs are going the way they are: last outcome and error, "
           "duration trend, and the quality checks recorded after each load.",
           ("*",), "connector:read", ActionKind.READ, ConnectionRef,
           capability="connectors"),
)

EXECUTORS: Dict[str, Callable] = {
    "connectors.list_sources": list_sources,
    "connectors.sync_history": sync_history,
    "connectors.quality_checks": quality_checks,
    "connectors.diagnose_sync": diagnose_sync,
}

RESOLVERS: Dict[str, Callable] = {
    "connectors.list_sources": _r("app.api.connectors", "list_connections"),
    "connectors.sync_history": _r("app.api.connectors", "get_sync_history"),
    "connectors.quality_checks": _r("app.api.connectors", "get_quality_checks"),
    "connectors.diagnose_sync": _r("app.api.connectors", "get_sync_history"),
}

PREVIEWERS: Dict[str, Callable] = {}
