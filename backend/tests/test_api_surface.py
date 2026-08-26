"""The developer-facing API surface, generated rather than typed.

The API page listed three endpoints because I typed three endpoints. The AI surface
is fourteen paths, and a hand-written list is the drift this branch has spent its
time removing everywhere else.

Everything here comes from the running application: the routes, the permission each
guard enforces (from the marker require_permission already sets), and a request
skeleton from the pydantic model the route actually validates against. Nothing is
restated, so nothing can disagree.
"""
import pytest

from app.api.api_surface import build_api_surface, example_from_schema


def test_the_surface_is_the_ai_routes_not_every_route():
    import main
    surface = build_api_surface(main.app)
    assert surface, "no routes found"
    assert all(e["path"].startswith("/api/ai/") for e in surface)


def test_it_finds_the_endpoints_an_application_actually_calls():
    import main
    paths = {e["path"] for e in build_api_surface(main.app)}
    for expected in ("/api/ai/search", "/api/ai/rag", "/api/ai/collections"):
        assert expected in paths, expected


def test_each_entry_names_the_permission_its_guard_enforces():
    """Read off require_permission's marker, so a route whose gate changes reports the
    change here without anyone editing this page."""
    import main
    search = next(e for e in build_api_surface(main.app)
                  if e["path"] == "/api/ai/search" and e["method"] == "POST")
    assert search["permission"] == "ai:generate"


def test_a_summary_comes_from_the_route_itself():
    import main
    rag = next(e for e in build_api_surface(main.app) if e["path"] == "/api/ai/rag")
    assert rag["summary"]


# ── request skeletons ─────────────────────────────────────────────────────────

def test_required_fields_appear_in_the_example():
    schema = {"properties": {"collection": {"type": "string"}, "query": {"type": "string"}},
              "required": ["collection", "query"]}
    assert example_from_schema(schema) == {"collection": "string", "query": "string"}


def test_optional_fields_with_defaults_are_shown_with_their_default():
    """Showing k with its real default answers "what happens if I leave it out"
    without anyone reading the source."""
    schema = {"properties": {"collection": {"type": "string"}, "k": {"type": "integer", "default": 5}},
              "required": ["collection"]}
    assert example_from_schema(schema)["k"] == 5


def test_optional_fields_without_a_default_are_left_out():
    schema = {"properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]}
    assert example_from_schema(schema) == {"a": "string"}


def test_an_endpoint_with_no_body_has_no_example():
    assert example_from_schema(None) is None


def test_types_are_rendered_as_something_a_person_can_edit():
    schema = {"properties": {"n": {"type": "integer"}, "flag": {"type": "boolean"},
                             "items": {"type": "array"}, "obj": {"type": "object"}},
              "required": ["n", "flag", "items", "obj"]}
    out = example_from_schema(schema)
    assert out == {"n": 0, "flag": False, "items": [], "obj": {}}
