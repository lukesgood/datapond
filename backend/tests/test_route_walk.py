"""app/route_walk.py is the one walker of app.routes (FastAPI 0.137+ keeps included
routers as one entry each; before this helper, the API surface found no routes)."""
from app.route_walk import api_routes, app_routes


def test_included_routes_come_back_flat_with_full_paths_and_their_guards():
    import main
    routes = {(r.path, m): r for r in api_routes(main.app) for m in r.methods}
    assert len(routes) > 300
    pause = routes[("/api/connectors/{connection_id}/pause", "POST")]
    guards = [getattr(d.call, "__datapond_authorization__", None) for d in pause.dependant.dependencies]
    assert any("connector:write" in str(g) for g in guards)


def test_every_route_has_a_set_of_methods_and_only_api_routes_are_api():
    import main
    everything = app_routes(main.app)
    assert all(isinstance(r.methods, set) for r in everything)
    assert any(not r.is_api for r in everything)            # docs, openapi.json, mounts
    assert all(r.is_api for r in api_routes(main.app))
