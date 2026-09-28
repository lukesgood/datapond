"""The OpenAPI document an agent gateway can register as a target.

FastAPI serves the whole app as OpenAPI 3.1, and every Optional field in it is an
`anyOf` with null. AgentCore Gateway — and gateways built the same way — refuse
anyOf/oneOf/allOf, want OpenAPI 3.0, take the tool name from `operationId`, and want
authentication configured on the gateway rather than in the document. Registering
DataPond meant hand-editing the spec, which is correct the day it is written and
wrong after the next field lands.

So the schemas here are read from the running app and only reduced: refs inlined,
`Optional[X]` rewritten as `X, nullable`, 3.1-only keywords turned into their 3.0
spelling. What is restated by hand is only the part a model reads — the tool's name
and what it is for — because a route docstring is written for whoever maintains it.

The document lists only the tools the requesting credential can call, so fetching it
with an agent's key yields exactly that agent's tool set.
"""
import copy
from dataclasses import dataclass
from typing import Iterable, List, Optional

OPENAPI_VERSION = "3.0.3"


@dataclass(frozen=True)
class Tool:
    path: str
    method: str
    operation_id: str
    description: str
    # Request fields a model should not set. They keep their server-side default.
    hide: frozenset = frozenset()


# What a model reads for a field whose model declares no description. A field that
# has one in its pydantic model keeps it; these only fill the gap.
FIELD_NOTES = {
    "collection": "Name of the knowledge collection to read.",
    "query": "What to search for, in natural language.",
    "question": "The question to answer, in natural language.",
    "k": "How many passages to retrieve (1-50).",
    "rerank": "Re-order passages with the rerank model. Omit for the deployment default.",
    "expand_concepts": "Also search for related terms of the query's concepts.",
    "context": "Optional extra context for the question, such as the tables of interest.",
}


TOOLS: List[Tool] = [
    Tool("/api/ai/search", "post", "search_knowledge",
         "Search a knowledge collection for passages relevant to a query. Returns the "
         "top matching chunks with their source and similarity score. Personal data is "
         "masked according to the collection's policy."),
    Tool("/api/ai/rag", "post", "answer_with_citations",
         "Answer a question from a knowledge collection. Retrieves relevant passages and "
         "returns a generated answer with numbered citations to the sources used."),
    Tool("/api/ai/sql", "post", "generate_sql",
         "Turn a natural-language question into a SQL query over the tables this caller "
         "may read. Generates the query only; it does not run it."),
    Tool("/api/queries/execute", "post", "run_sql",
         "Run a read-only SQL query. Row-level security and column masking apply to the "
         "caller, and personal data in the result is masked.",
         # History is always recorded for a service account, and origin is a label
         # the UI sets; neither is a choice a model should be offered.
         hide=frozenset({"save_history", "origin"})),
]

_ERRORS = {
    "400": "The request was refused, for example a statement this caller may not run.",
    "401": "The credential is missing, invalid, revoked or expired.",
    "402": "The caller has spent its model budget.",
    "403": "The caller lacks the permission this tool requires.",
    "429": "Over the key's request budget; retry after the Retry-After header.",
}

# Keys that describe a schema in 3.1 but mean nothing, or something else, in 3.0.
_DROP = {"$schema", "$defs", "$id", "const", "examples", "contentMediaType"}


def _resolve(ref: str, components: dict) -> dict:
    return components.get(ref.rsplit("/", 1)[-1], {})


def _to_30(node, components: dict, seen: tuple = ()):
    """A 3.0 schema with no refs and no composition, from a FastAPI 3.1 one."""
    if isinstance(node, list):
        return [_to_30(n, components, seen) for n in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        if name in seen:
            # A recursive model. A gateway cannot inline it and cannot follow a ref,
            # so it is described as an object and the recursion ends here.
            return {"type": "object"}
        merged = {**_resolve(node["$ref"], components),
                  **{k: v for k, v in node.items() if k != "$ref"}}
        return _to_30(merged, components, seen + (name,))

    out = {}
    nullable = False
    for key in ("anyOf", "oneOf", "allOf"):
        if key in node:
            branches = [b for b in node[key] if b.get("type") != "null"]
            nullable = nullable or len(branches) < len(node[key])
            # allOf of one branch is how pydantic attaches a description to a ref.
            # Several real alternatives cannot be said without composition; the first
            # is the one the field was declared with, and the description remains.
            if branches:
                out.update(_to_30(branches[0], components, seen))

    for key, value in node.items():
        if key in ("anyOf", "oneOf", "allOf") or key in _DROP:
            continue
        if key == "type" and isinstance(value, list):
            types = [t for t in value if t != "null"]
            nullable = nullable or len(types) < len(value)
            out["type"] = types[0] if types else "string"
        elif key in ("exclusiveMinimum", "exclusiveMaximum") and not isinstance(value, bool):
            bound = "minimum" if key == "exclusiveMinimum" else "maximum"
            out[bound] = value
            out[key] = True
        elif key == "properties":
            out[key] = {name: _to_30(prop, components, seen) for name, prop in value.items()}
        elif key == "default" and value is None:
            continue
        else:
            out[key] = _to_30(value, components, seen)

    if "examples" in node and isinstance(node["examples"], list) and node["examples"]:
        out["example"] = node["examples"][0]
    if "const" in node:
        out["enum"] = [node["const"]]
    if nullable:
        out["nullable"] = True
    return out


def _json_schema(content: Optional[dict], components: dict) -> dict:
    schema = ((content or {}).get("application/json") or {}).get("schema")
    return _to_30(schema, components) if schema else {"type": "object"}


def _permission_of(app, path: str, method: str) -> Optional[str]:
    from app.api.api_surface import _permission
    for route in app.routes:
        if getattr(route, "path", None) == path and method.upper() in getattr(route, "methods", ()):
            return _permission(route)
    return None


def build_tool_openapi(app, server_url: str, permissions: Iterable[str]) -> dict:
    """The gateway-ready document for the tools a holder of `permissions` can call."""
    full = app.openapi()
    components = (full.get("components") or {}).get("schemas") or {}
    held = set(permissions)
    paths: dict = {}
    for tool in TOOLS:
        source = ((full.get("paths") or {}).get(tool.path) or {}).get(tool.method)
        if not source:
            continue
        needed = _permission_of(app, tool.path, tool.method)
        if needed and ":" in needed and not needed.startswith("role:") and needed not in held:
            continue
        responses = {"200": {
            "description": "Success",
            "content": {"application/json": {"schema": _json_schema(
                (source.get("responses") or {}).get("200", {}).get("content"), components)}},
        }}
        responses.update({code: {"description": text} for code, text in _ERRORS.items()})
        op = {
            "operationId": tool.operation_id,
            "summary": tool.operation_id.replace("_", " "),
            "description": tool.description,
            "responses": responses,
        }
        body = (source.get("requestBody") or {}).get("content")
        if body:
            schema = _json_schema(body, components)
            props = schema.get("properties") or {}
            for name in tool.hide:
                props.pop(name, None)
            if "required" in schema:
                schema["required"] = [f for f in schema["required"] if f not in tool.hide]
            for name, prop in props.items():
                prop.pop("title", None)
                if not prop.get("description") and name in FIELD_NOTES:
                    prop["description"] = FIELD_NOTES[name]
            schema.pop("title", None)
            op["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": schema}},
            }
        paths[tool.path] = {tool.method: op}

    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": "DataPond tools",
            "version": (full.get("info") or {}).get("version", "1.0.0"),
            "description": "Governed search, cited answers and SQL. Authenticate with a "
                           "service-account key sent as 'Authorization: Bearer <key>', "
                           "configured on the gateway's outbound credential.",
        },
        "servers": [{"url": server_url.rstrip("/")}],
        "paths": copy.deepcopy(paths),
    }
