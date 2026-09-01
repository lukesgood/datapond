"""No (method, path) pair is declared twice across the whole application.

FastAPI serves whichever declaration comes first for a given (method, path); a
second declaration of the same route is silently unreachable dead code that a
reader will nonetheless find and edit one day, believing it does something.
POST /mlflow/experiments was declared twice in mlflow_integration.py (once as
`create_experiment`, once — 650 lines later — as `create_experiment_alias`); this
is a whole-application property, not a one-off check of that single file, so it
covers every router mounted on `main.app`, not just MLflow's.

`main.app.routes` is not just this application's declared API endpoints. It also
carries FastAPI's own built-in routes (`/openapi.json`, `/docs`,
`/docs/oauth2-redirect`, `/redoc` — plain Starlette `Route` objects, not
`fastapi.routing.APIRoute`), a websocket route (`APIWebSocketRoute`, which has no
HTTP `methods` at all), and would carry any `Mount`-ed static file server too.
None of those are declared by this application's own `@router.get/post/...`
decorators, so none of them can suffer the copy-paste-duplicate-route defect this
test exists to catch — and including them would either fail on FastAPI's own
plumbing (which this project does not own and cannot fix) or silently skip real
duplicates if a broader-but-wrong filter were used instead. Restricting to
`isinstance(route, APIRoute)` keeps the test to exactly this application's
declared API surface.
"""
from collections import Counter

from fastapi.routing import APIRoute


def _declared_pairs():
    import main
    for route in main.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            yield method, route.path


def test_no_method_path_pair_is_declared_more_than_once():
    counts = Counter(_declared_pairs())
    dupes = sorted(f"{method} {path} (x{n})"
                    for (method, path), n in counts.items() if n > 1)
    assert not dupes, (
        f"{len(dupes)} route(s) declared more than once — FastAPI serves only the "
        "first declaration; the rest are unreachable dead code:\n  "
        + "\n  ".join(dupes)
    )


def test_the_detector_actually_finds_routes():
    """Guards the detector itself: if the APIRoute filter stopped matching
    anything, the test above would report zero pairs and pass while checking
    nothing."""
    pairs = list(_declared_pairs())
    assert len(pairs) > 100, f"detector found only {len(pairs)} declared route(s)"
