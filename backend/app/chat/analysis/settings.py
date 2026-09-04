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

None of the three settable keys touches embeddings. `ai.litellm_model` maps to
`LITELLM_MODEL` (app/api/system_settings.py) — the *generation* model used for chat
and cited answers. What a collection is embedded with, and what a query is embedded
with, is `AI_EMBED_MODEL` (`_embed_model()` in app/api/ai_vectors.py) — a different
env var, not in `AI_ENV_MAP`, and so not reachable through this action at all. A
collection-stranding check against `ai.litellm_model` would therefore describe a
change this action cannot make; `dependents_set_model_config` does not attempt one.

What every one of the three keys *does* do is change how or with which model every
later call is served — `ai.litellm_model` for generation calls, `ai.provider` and
`ai.litellm_url` for the shared gateway path that both generation and embedding calls
go through (`_gateway()` in app/api/ai_vectors.py reads `LITELLM_URL` once for both).
`dependents_set_model_config` says that plainly for whichever key is being changed,
rather than computing a list it cannot support.
"""
from typing import Any, Callable, Dict

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r
from app.chat.dependents import Dependents

from app.api.system_settings import AI_ENV_MAP, SENSITIVE_KEYS

# Derived, not written out — see module docstring.
ALLOWED_KEYS = set(AI_ENV_MAP) - set(SENSITIVE_KEYS)

# The keys named in both the action description and the params field description
# below (fix round 1): `named_by_user` only accepts the person's own words, and for
# a dotted key like "ai.litellm_model" that means either the full key or its
# trailing segment ("litellm_model") verbatim — "change the model" does not match.
# The model reading this schema has to be told to ask the person which of these
# three keys they mean, rather than proposing against prose the gate will refuse.
_KEY_LIST = "ai.provider, ai.litellm_url, ai.litellm_model"


class SetModelConfigParams(_Strict):
    key: str = Field(
        ...,
        description=(
            f"The exact settings key to change, one of: {_KEY_LIST}. Only propose "
            f"this action once the person has said which one themselves, by name — "
            f"'the model' or 'the settings' alone does not identify one of these "
            f"three. If they haven't said which, ask before proposing."))
    value: Any


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
    """A truthful consequence for each of the three settable keys — never an empty
    `items` with an empty `not_checked`, which `Dependents`' own docstring says reads
    as "nothing depends on this". None of the three can strand a collection (see the
    module docstring), so this does not compute a per-collection list; it says what
    actually happens instead."""
    import os

    d = Dependents("settings.set_model_config")
    key = params.get("key")
    value = params.get("value")

    if key not in ALLOWED_KEYS:
        d.skipped(f"{key!r} is not a settings key this action recognises, so what "
                  f"depends on it could not be determined.")
        return d.done()

    current = os.getenv(AI_ENV_MAP[key], "")

    if key == "ai.litellm_model":
        d.item("generation", "every chat reply and cited answer",
               f"Asks the gateway to run {value!r} instead of {current!r}, "
               f"immediately, for every generation call after this change. "
               f"Collections and their embeddings are unaffected — retrieval is "
               f"keyed on AI_EMBED_MODEL, a separate setting this action cannot "
               f"change.")
    else:
        d.item("routing", "every chat, cited answer, and document/query embedding",
               f"{key} feeds the one gateway path all of them share — changing it "
               f"from {current!r} to {value!r} repoints every one of them "
               f"immediately, not just new conversations.")
    return d.done()


ACTIONS = (
    Action("settings.set_model_config", "Change model configuration",
           f"Change one non-credential AI setting: {_KEY_LIST}. The person must "
           "name which setting themselves — if they haven't, ask (e.g. 'which "
           "setting: provider, litellm_url, or litellm_model?') rather than "
           "proposing against 'the model' or 'the settings' generically. Every "
           "one of the three changes how or with what model later calls are "
           "served, immediately — provider and litellm_url repoint the shared "
           "gateway path chat, cited answers, and embeddings all use.",
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
