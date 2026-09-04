"""Changing model configuration, with credentials permanently out of reach.

`AI_ENV_MAP` (app/api/system_settings.py) is every settable key. `SENSITIVE_KEYS` is
the subset that holds a credential. `ALLOWED_KEYS` here is the *difference* of those
two sets, computed once at import — never a list typed out by hand. Typed out, a
credential added to `SENSITIVE_KEYS` next year stays reachable through this action
until someone remembers this file exists and edits it too. Derived, it is excluded
automatically, by construction, the moment it is added to `SENSITIVE_KEYS`.

The settings body the underlying route accepts (`SettingsPatch.settings`) is a
`dict[str, Any]` — a pydantic model's `extra="forbid"` never reaches inside a dict
field, so a key outside `ALLOWED_KEYS` cannot be refused by the params schema alone.
`set_model_config` below refuses it again, at execution, before a `SettingsPatch` is
even constructed.

Changing `ai.litellm_model` changes which model queries embed against. A collection
embedded under the old model and searched under the new one degrades silently — no
error, no log line, just worse retrieval — which is exactly what
`knowledge.diagnose_collection` was built to detect after the fact (see
app/chat/analysis/knowledge.py). `dependents_set_model_config` below names the
collections that would be stranded *before* the change is approved.
"""
import inspect
from typing import Any, Callable, Dict, List, Optional

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r
from app.chat.dependents import Dependents

from app.api.system_settings import AI_ENV_MAP, SENSITIVE_KEYS

# Derived, not written out — see module docstring.
ALLOWED_KEYS = set(AI_ENV_MAP) - set(SENSITIVE_KEYS)

# The only key among ALLOWED_KEYS that selects the model queries run against, and so
# the only one a stranded-collection check makes sense for. `ai.provider` and
# `ai.litellm_url` change how a model is reached, not which one is active.
_MODEL_KEYS = {"ai.litellm_model"}


class SetModelConfigParams(_Strict):
    key: str
    value: Any


async def _maybe_await(value: Any) -> Any:
    """`_collections_by_embed_model` is a real `async def`, but tests replace it with
    a plain synchronous callable — same reason governance.py has its own copy of
    this: a dependents callable may or may not be a coroutine, and the caller
    should not have to know which."""
    if inspect.isawaitable(value):
        return await value
    return value


async def _collections_by_embed_model() -> List[dict]:
    """Every collection's name and the model it was embedded with."""
    from app.api.auth import _get_pool

    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name, embed_model FROM ai_collections")
    return [{"name": r["name"], "embed_model": r["embed_model"]} for r in rows]


async def set_model_config(params: dict, user: dict) -> dict:
    key = params.get("key")
    value = params.get("value")

    # Refused before a SettingsPatch is even built — the params schema alone cannot
    # do this, because `settings` is a dict field and `extra="forbid"` does not
    # reach inside it.
    if key not in ALLOWED_KEYS:
        raise ValueError(
            f"{key!r} is not a settable model-configuration key, or it holds a "
            f"credential this action will never write.")

    from app.api import system_settings

    patch = system_settings.SettingsPatch(settings={key: value})
    return await system_settings.update_system_settings(patch)


async def preview_set_model_config(params: dict, user: dict) -> dict:
    key = params.get("key")
    value = params.get("value")
    if key not in ALLOWED_KEYS:
        return {"key": key,
                "summary": f"{key!r} cannot be set here — not a recognised, "
                          f"non-credential configuration key."}
    return {"key": key, "value": value, "summary": f"Set {key} to {value!r}."}


async def dependents_set_model_config(params: dict, user: dict) -> dict:
    d = Dependents("settings.set_model_config")
    key = params.get("key")
    value = params.get("value")

    if key not in _MODEL_KEYS:
        # Genuinely nothing to check — ai.provider / ai.litellm_url change how the
        # model is reached, not which embeddings it must match. An empty items list
        # is correct here because nothing was skipped, not because nothing was read.
        return d.done()

    try:
        collections = await _maybe_await(_collections_by_embed_model())
    except Exception as e:
        d.skipped(f"Could not read ai_collections to check which collections this "
                  f"model change would strand: {e}")
        return d.done()

    for c in collections or []:
        embed_model = c.get("embed_model")
        if embed_model != value:
            d.item("collection", c.get("name"),
                   f"Embedded with {embed_model!r}; queries will use {value!r} after "
                   f"this change — retrieval degrades with nothing logged.")
    return d.done()


ACTIONS = (
    Action("settings.set_model_config", "Change model configuration",
           "Change a non-credential AI setting: provider, gateway URL, or the "
           "active model name. Changing the model can strand collections embedded "
           "with a different one.",
           ("*",), "settings:write", ActionKind.DESTRUCTIVE, SetModelConfigParams,
           target_field="key"),
)

EXECUTORS: Dict[str, Callable] = {
    "settings.set_model_config": set_model_config,
}

RESOLVERS: Dict[str, Callable] = {
    "settings.set_model_config": _r("app.api.system_settings", "update_system_settings"),
}

PREVIEWERS: Dict[str, Callable] = {
    "settings.set_model_config": preview_set_model_config,
}

DEPENDENTS: Dict[str, Callable] = {
    "settings.set_model_config": dependents_set_model_config,
}
