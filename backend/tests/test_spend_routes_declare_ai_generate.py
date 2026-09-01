"""A route that spends model tokens declares `ai:generate`. As a property, not a list.

F3 in docs/superpowers/plans/2026-09-01-persona-usability.md, and it exists because the
list failed. `/ai/search`, `/ai/rag` and `/ai/embed` were given `ai:generate` one at a
time, each after someone noticed; `POST /ai/collections/{name}/ingest` followed later
for the same reason; and `ingest-source` and `schedule` shipped requiring
`knowledge:write` and nothing else — six commits after the sibling route was fixed on
exactly that argument. Every one of those was caught by reading, and the reading is
what kept missing one.

So this file does not name routes. It finds them:

  1. **Seeds.** A function that POSTs to the model gateway — `/v1/embeddings`,
     `/v1/rerank`, `/v1/chat/completions` — spends money. Those three literals are how
     spend is written in this codebase, and they are what the LiteLLM gateway bills on.
  2. **Reverse reachability.** Anything that calls a seed spends too, transitively,
     across modules.
  3. **The assertion.** Every route in the running application whose handler is in that
     set declares `ai:generate` — read from the guards' own
     `__datapond_authorization__`, the same declaration the route inventory uses.

What it cannot see, stated so nobody mistakes a pass for a proof: a call made through a
variable, a registry lookup, `getattr`, or a background task started with
`asyncio.create_task` and no direct call edge. It resolves plain calls — `f()`,
`module.f()`, and names bound by an `import` at module level or inside a function body,
which is this repo's common shape. That covers every spend path in the application
today and every one that has gone wrong so far.
"""
import ast
from pathlib import Path

import pytest
from fastapi import routing

APP = Path(__file__).resolve().parents[1] / "app"

# How spending is written here. Not a heuristic: these are the three OpenAI-compatible
# endpoints the LiteLLM gateway bills for, and every model call in the application goes
# through one of them.
GATEWAY_PATHS = ("/v1/embeddings", "/v1/rerank", "/v1/chat/completions")

SPEND_PERMISSION = "ai:generate"


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(APP.parent).with_suffix("").parts)


def _functions_and_imports():
    """(defs, imports) for every module under app/.

    defs:    {(module, funcname): ast.FunctionDef}
    imports: {(module, localname): (source_module, original_name)} — module-level and
             function-local `import` / `from … import`, because this codebase imports
             inside functions constantly to break cycles.
    """
    defs, imports = {}, {}
    for path in sorted(APP.rglob("*.py")):
        module = _module_name(path)
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:                       # not ours to fix here
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs[(module, node.name)] = node
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    imports[(module, alias.asname or alias.name)] = (node.module, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports[(module, alias.asname or alias.name)] = (alias.name, None)
    return defs, imports


def _callees(func: ast.AST, module: str, defs: dict, imports: dict) -> set:
    """Every (module, name) this function calls that we can resolve."""
    found = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            name = target.id
            if (module, name) in defs:
                found.add((module, name))
            elif (module, name) in imports:
                source, original = imports[(module, name)]
                found.add((source, original or name))
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            owner, name = target.value.id, target.attr
            if (module, owner) in imports:
                source, _ = imports[(module, owner)]
                found.add((source, name))
            # `self.x()` / an instance method: unresolvable by name alone, and named in
            # the module docstring as a known blind spot.
    return found


def _spending_functions() -> set:
    """Every function that reaches a gateway call, directly or through other functions."""
    defs, imports = _functions_and_imports()

    seeds = set()
    for (module, name), node in defs.items():
        body = ast.dump(node)
        if any(path in body for path in GATEWAY_PATHS):
            seeds.add((module, name))
    assert seeds, "no function POSTs to the model gateway — the seeds are wrong"

    # Reverse edges, then breadth-first from the seeds outward.
    callers = {}
    for key, node in defs.items():
        for callee in _callees(node, key[0], defs, imports):
            callers.setdefault(callee, set()).add(key)

    spending, frontier = set(seeds), list(seeds)
    while frontier:
        current = frontier.pop()
        for caller in callers.get(current, ()):
            if caller not in spending:
                spending.add(caller)
                frontier.append(caller)
    return spending


def _declared_permissions(route) -> set:
    """What this route's guards say they enforce, from their own declarations."""
    import inspect

    declared = set()
    for dependency in route.dependant.dependencies:
        declared.add(getattr(dependency.call, "__datapond_authorization__", None))
    for parameter in inspect.signature(route.endpoint).parameters.values():
        call = getattr(parameter.default, "dependency", None)
        if call is not None:
            declared.add(getattr(call, "__datapond_authorization__", None))
    return {d for d in declared if d}


def _spending_routes():
    import main

    spending = _spending_functions()
    out = []
    for route in main.app.routes:
        if not isinstance(route, routing.APIRoute):
            continue
        endpoint = route.endpoint
        key = (getattr(endpoint, "__module__", ""), getattr(endpoint, "__name__", ""))
        if key in spending:
            out.append((route, key))
    return out


def test_the_seeds_find_the_calls_that_actually_bill():
    """Guard against the walker silently finding nothing — a green suite because the
    analysis broke is the failure mode this whole file is meant to avoid."""
    spending = _spending_functions()
    assert ("app.api.ai_vectors", "_embed") in spending
    assert ("app.api.ai_vectors", "_rerank") in spending
    assert len(spending) > 5, f"only {len(spending)} spending functions found — suspicious"


def test_the_walker_finds_the_routes_everyone_already_knows_spend():
    """If search, rag and embed are not in the result, the route side is broken and
    every assertion below is vacuous."""
    names = {key[1] for _route, key in _spending_routes()}
    for known in ("search", "rag", "embed"):
        assert known in names, f"the walker lost /{known} — it cannot be trusted"


@pytest.mark.parametrize(
    "route,key",
    _spending_routes(),
    ids=lambda value: value if isinstance(value, tuple) else "",
)
def test_every_route_that_spends_declares_ai_generate(route, key):
    declared = _declared_permissions(route)
    assert SPEND_PERMISSION in declared, (
        f"{sorted(route.methods)[0]} {route.path} ({key[0]}.{key[1]}) reaches the model "
        f"gateway but declares {sorted(declared) or 'nothing'}. A caller without "
        f"'{SPEND_PERMISSION}' can spend money through it."
    )
