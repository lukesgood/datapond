"""The OpenAPI document an agent gateway can register as a target.

FastAPI serves OpenAPI 3.1 with `anyOf` for every Optional field, and AgentCore
Gateway refuses anyOf/oneOf/allOf outright. Registering DataPond behind one meant
hand-editing the spec — which drifts from the routes the day after it is written.
This document is generated from the running app, so it cannot drift, and is
reduced to what a gateway accepts.
"""
import json
import re

from fastapi.testclient import TestClient

from app.tool_openapi import TOOLS, build_tool_openapi

ALL_PERMS = {"ai:generate", "query:run", "knowledge:read"}


def _app_spec():
    import main
    return main.app


def _walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path, k, v
            yield from _walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}/{i}")


def test_it_contains_exactly_the_tools():
    spec = build_tool_openapi(_app_spec(), "https://dp.example.com", ALL_PERMS)
    ops = {op["operationId"] for item in spec["paths"].values() for op in item.values()}
    assert ops == {t.operation_id for t in TOOLS}
    assert set(spec["paths"]) == {t.path for t in TOOLS}


def test_nothing_a_gateway_refuses_survives():
    spec = build_tool_openapi(_app_spec(), "https://dp.example.com", ALL_PERMS)
    for where, key, value in _walk(spec):
        assert key not in ("anyOf", "oneOf", "allOf"), f"{key} at {where}"
        assert key != "$ref", f"unresolved $ref at {where}"
        assert key not in ("securitySchemes", "security"), f"{key} at {where}"
        if key == "type":
            assert isinstance(value, str), f"3.1 type list at {where}"
        if key in ("exclusiveMinimum", "exclusiveMaximum"):
            assert isinstance(value, bool), f"3.1 numeric {key} at {where}"


def test_it_is_openapi_3_0_with_a_static_server():
    spec = build_tool_openapi(_app_spec(), "https://dp.example.com/", ALL_PERMS)
    assert spec["openapi"].startswith("3.0")
    assert spec["servers"] == [{"url": "https://dp.example.com"}]


def test_optional_fields_become_nullable_not_anyof():
    spec = build_tool_openapi(_app_spec(), "https://dp.example.com", ALL_PERMS)
    body = spec["paths"]["/api/ai/search"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    nullable = [p for p in body["properties"].values() if p.get("nullable")]
    assert nullable, "an Optional field lost its null instead of becoming nullable"
    assert all("type" in p for p in nullable)


def test_names_fit_a_model_tool_spec():
    spec = build_tool_openapi(_app_spec(), "https://dp.example.com", ALL_PERMS)
    name = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
    for item in spec["paths"].values():
        for op in item.values():
            assert name.match(op["operationId"])
            assert op.get("description"), "the description is what the model reads"
    for where, key, value in _walk(spec):
        if key == "properties":
            for prop in value:
                assert name.match(prop), f"property {prop!r} at {where}"


def test_a_caller_only_sees_the_tools_it_can_call():
    spec = build_tool_openapi(_app_spec(), "https://dp.example.com", {"ai:generate"})
    ops = {op["operationId"] for item in spec["paths"].values() for op in item.values()}
    assert "run_sql" not in ops and "search_knowledge" in ops


def test_the_route_serves_it_to_any_signed_in_caller(monkeypatch):
    import main
    from app.api import auth

    user = {"id": "svc-1", "username": "svc-agent", "role": "ai_engineer",
            "auth_method": "service", "permissions": ["ai:generate"]}

    async def _user(_creds):
        return user
    monkeypatch.setattr(auth, "get_current_user", _user)
    main.app.dependency_overrides[auth.require_user] = lambda: user
    monkeypatch.setenv("APP_BASE_URL", "https://dp.example.com")
    try:
        r = TestClient(main.app).get("/api/tools/openapi.json",
                                     headers={"Authorization": "Bearer x"})
    finally:
        main.app.dependency_overrides.pop(auth.require_user, None)
    assert r.status_code == 200, r.text
    spec = r.json()
    assert spec["servers"][0]["url"] == "https://dp.example.com"
    assert "run_sql" not in json.dumps(spec)


def test_run_sql_does_not_offer_the_ui_only_fields():
    spec = build_tool_openapi(_app_spec(), "https://dp.example.com", ALL_PERMS)
    body = spec["paths"]["/api/queries/execute"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert set(body["properties"]) == {"query"}


def test_every_request_field_says_what_it_is_for():
    spec = build_tool_openapi(_app_spec(), "https://dp.example.com", ALL_PERMS)
    for path, item in spec["paths"].items():
        body = item["post"]["requestBody"]["content"]["application/json"]["schema"]
        for name, prop in body["properties"].items():
            assert prop.get("description"), f"{path} {name} has nothing for a model to read"
