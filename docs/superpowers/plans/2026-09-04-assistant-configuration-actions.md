# Assistant Configuration Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the assistant change configuration, behind a gate whose friction is proportional to what the change costs to undo.

**Architecture:** `ActionKind.DESTRUCTIVE` gains members. A destructive action carries three server-computed fields — the canonical `target` a person must type, the `dependents` that change, and `named_by_user`, which is true only when the target appears in something the *user* wrote. Reversible configuration uses the preview → approve card that already exists.

**Tech Stack:** Python 3.11, FastAPI, pydantic v2, asyncpg, pytest. Frontend: Next.js/React.

**Spec:** `docs/superpowers/specs/2026-09-04-assistant-configuration-actions-design.md` — read it first; this plan argues from it.

## Global Constraints

- The grading rule, verbatim from spec §3: **an action is destructive when undoing it needs information the product no longer holds, or when it changes who can do what. Everything else is a mutate.**
- No action may write a credential or read one back into a card (spec §2, §7).
- No action deletes an account, runs a sync, or deletes a collection or dashboard (spec §2).
- `named_by_user` is computed from **user-role turns only**. Anything the assistant said is not evidence (spec §5).
- Approval posts the invocation id and `typed_target`. It never re-sends parameters.
- A `dependents` list that could not be computed is never rendered as empty (spec §6).
- Every params model subclasses `_Strict`; action ids are `domain.verb`; executors call service functions directly, never HTTP routes.
- Tests: `cd backend && python3.12 -m pytest <paths> -q`. Local `python3` is 3.9 and unrelated modules fail to collect on `X | Y` annotations; CI runs 3.11. Frontend: `npm test`, `npx tsc --noEmit -p tsconfig.json`, and `npm run build` — the build is the only one that catches a dropped JSX tag.
- Async tests use `def _run(c): return asyncio.run(c)`, copied from `backend/tests/test_chat_human_only.py`. **Do not add pytest-asyncio.**
- **Some implementation steps are prose, on purpose.** Where a step tells you to build a
  pydantic body (`RlsPolicyIn`, `MaskPolicyIn`, `ScheduleRequest`, `MemberGrant`), this
  plan does not show the constructor call. Its author has not read those models field by
  field, and inventing plausible field names is exactly how the previous branch shipped a
  crash and a silently disabled feature. Read the model, then write the call. A prose step
  here means "the plan will not guess", not "the plan is unfinished".
- **Read every handler's real signature and return shape before writing an executor.** The analysis branch shipped a crash and a silently disabled feature from assuming payload shapes, and its mocks encoded the same assumption, so the tests passed for the wrong reason.

## Decisions already taken, so no task re-opens them

- **`spend.set_budget_alert` is NOT built.** Spec §9 flagged it as unresolved and said to drop it rather than invent it. Resolved: `/settings/ai/budget-alerts` is a **GET** whose `threshold: float = 80.0` is a query parameter on a report — "which keys are over N% of budget". There is no stored threshold to set. What remains is **eleven actions** — the spec's catalogue has ten rows after this one goes, but `knowledge.add_member / remove_member` is one row holding two actions. Seven are mutates and four are destructive.
- **No migration.** `chat_action_invocations` has a fixed column list, but `preview` is `jsonb` and the three new fields are server-computed card content. They go in `preview`. The authorization evidence is additionally written through the existing `record_audit` path, which is where an investigation looks.
- **The settings allowlist is derived, not written.** `backend/app/api/system_settings.py` already defines `AI_ENV_MAP` (five keys) and `SENSITIVE_KEYS` (two). The allowlist is the difference: `ai.provider`, `ai.litellm_url`, `ai.litellm_model`. Deriving it means a credential added to `SENSITIVE_KEYS` later is excluded without anyone remembering to.

---

## File structure

**Created:**

| File | Responsibility |
|---|---|
| `backend/app/chat/naming.py` | Whether a target was named by the user, and the normalisation that decides it |
| `backend/app/chat/dependents.py` | The shape a dependents list takes, and its "could not compute" case |
| `backend/app/chat/analysis/settings.py` | `settings.set_model_config` |
| `backend/app/chat/analysis/users.py` | `users.grant_role` |
| `frontend/components/chat/destructive-card.tsx` | Type-to-confirm card with the dependents list |

**Modified:**

| File | Change |
|---|---|
| `backend/app/chat/actions.py` | `Action.target_field`; destructive actions declared |
| `backend/app/chat/gate.py` | Destructive branch in `propose`; `typed_target` in `approve` |
| `backend/app/api/chat_routes.py` | Pass user turns to propose; `typed_target` on the approve route; prompt copy |
| `backend/app/chat/analysis/knowledge.py` | `set_refresh_schedule`, `add_member`, `remove_member` |
| `backend/app/chat/analysis/connectors.py` | `set_schedule`, `set_sync_mode` |
| `backend/app/chat/analysis/governance.py` | policy create ×2, policy delete ×2, their dependents |
| `frontend/components/chat/assistant-panel.tsx` | Render the destructive card; greeting copy |

---

## Task 1: Whether the user named it

**Files:**
- Create: `backend/app/chat/naming.py`
- Test: `backend/tests/test_chat_naming.py`

**Interfaces:**
- Produces: `named_by_user(target: str, turns: Sequence[Mapping]) -> Optional[dict]` — returns the evidence (`{"turn_index": int, "matched": str}`) when the target was named, or `None`. Also `normalise(text: str) -> str` and `segments(target: str) -> list[str]`.

A pure function with no I/O, tested alone. It is the load-bearing part of the spec and the only part an attacker aims at.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_naming.py
"""Did the person actually name this thing?

The assistant may not put a confirmation dialog in front of someone for a target
they never mentioned. What counts as "mentioned" is only ever something the USER
wrote — never something the assistant said, because the assistant repeats what it
read, and what it read includes table comments, column names and document chunks
that anyone with write access to a source can author.
"""
from app.chat.naming import named_by_user, normalise, segments


def _user(text):
    return {"role": "user", "content": text}


def _assistant(text):
    return {"role": "assistant", "content": text}


def test_a_target_the_user_typed_is_named():
    ev = named_by_user("crm.customers", [_user("drop the crm.customers policy")])
    assert ev and ev["turn_index"] == 0


def test_a_target_only_the_assistant_mentioned_is_not_named():
    """The laundering case, and the reason this module exists."""
    assert named_by_user("crm.customers", [
        _user("clean up whatever looks unused"),
        _assistant("I found a policy on crm.customers that looks unused."),
    ]) is None


def test_a_target_nobody_mentioned_is_not_named():
    assert named_by_user("crm.customers", [_user("tidy up the policies")]) is None


def test_the_trailing_segment_counts():
    """People say "the customers policy", not "the crm.customers policy"."""
    assert named_by_user("crm.customers", [_user("delete the customers policy")])


def test_a_different_table_in_the_same_namespace_does_not_count():
    assert named_by_user("crm.customers", [_user("delete the crm.orders policy")]) is None


def test_case_quotes_and_backticks_do_not_matter():
    for written in ['delete `CRM.Customers`', 'delete "crm.customers"', "delete CRM.CUSTOMERS"]:
        assert named_by_user("crm.customers", [_user(written)]), written


def test_slash_and_colon_separate_too():
    assert named_by_user("iceberg:default/events", [_user("drop the events one")])


def test_the_evidence_names_the_turn_and_what_matched():
    """"Why was this allowed" is asked later, and the answer should not require
    reconstructing a conversation nobody kept."""
    ev = named_by_user("crm.customers", [_user("hi"), _user("delete crm.customers")])
    assert ev == {"turn_index": 1, "matched": "crm.customers"}


def test_an_empty_or_whitespace_target_is_never_named():
    """A target the server could not derive must not be waved through by a stray space."""
    for bad in ("", "   ", None):
        assert named_by_user(bad, [_user("delete everything")]) is None


def test_a_one_character_segment_does_not_match_by_accident():
    """Short segments would match almost any sentence; they need the whole name."""
    assert named_by_user("a.b", [_user("delete the b thing")]) is None
    assert named_by_user("a.b", [_user("delete a.b")])


def test_normalise_and_segments_are_the_documented_rule():
    assert normalise(' "CRM.Customers" ') == "crm.customers"
    assert segments("iceberg:default/events") == ["iceberg", "default", "events"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_naming.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.naming'`.

- [ ] **Step 3: Write the module**

```python
# backend/app/chat/naming.py
"""Whether the person named the target themselves.

The corpus is the user's own turns. The assistant's turns are excluded, and that
exclusion is the whole mechanism: the assistant repeats what it read, and what it read
includes table comments, column names and document chunks that anyone with write access
to a source can author. Without this, "delete the policy on crm.customers" written into
a column description would arrive as though the user had asked for it.

Typing the target at approval is the second line. This is the first, and it runs before
a card is ever rendered.
"""
import re
from typing import List, Mapping, Optional, Sequence

# Anything shorter matches too much prose to mean anything.
_MIN_SEGMENT = 2

_SEPARATORS = re.compile(r"[./:]+")
_STRIP = '\'"`  \t\n'


def normalise(text: str) -> str:
    """Casefolded, with the quoting people add around identifiers removed."""
    return (text or "").strip(_STRIP).strip().casefold()


def segments(target: str) -> List[str]:
    """The parts of a dotted, slashed or colon-separated name."""
    return [s for s in _SEPARATORS.split(normalise(target)) if s]


def named_by_user(target: Optional[str],
                  turns: Sequence[Mapping]) -> Optional[dict]:
    """Evidence that the user named `target`, or None.

    Returns the first match as `{"turn_index": int, "matched": str}` — the index is
    into `turns` as given, so the record points at a turn someone can go and read.
    """
    whole = normalise(target or "")
    if not whole:
        return None

    parts = segments(whole)
    # The full name always counts. A trailing segment counts too, because people say
    # "the customers policy" — but only when it is long enough to mean something.
    candidates = [whole]
    if parts and len(parts[-1]) >= _MIN_SEGMENT and parts[-1] != whole:
        candidates.append(parts[-1])

    for index, turn in enumerate(turns or ()):
        if (turn or {}).get("role") != "user":
            continue
        haystack = normalise(str((turn or {}).get("content") or ""))
        for candidate in candidates:
            if re.search(rf"(?<![\w.:/]){re.escape(candidate)}(?![\w.:/])", haystack):
                return {"turn_index": index, "matched": candidate}
    return None
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_naming.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/naming.py backend/tests/test_chat_naming.py
git commit -m "feat(assistant): whether the user named the target, from their turns only

The assistant repeats what it read, and what it read includes table comments and
document chunks that anyone with write access to a source can author. Evidence
that the user asked for something can only be something the user wrote."
```

---

## Task 2: The dependents shape

**Files:**
- Create: `backend/app/chat/dependents.py`
- Test: `backend/tests/test_chat_dependents.py`

**Interfaces:**
- Produces: `Dependents(subject: str)` with `.item(kind, name, effect)`, `.skipped(reason)`, `.done() -> dict` returning `{"subject", "items", "not_checked"}`.

Same reasoning as `Diagnosis` in the analysis branch, and deliberately the same shape of honesty: a list that could not be computed is not an empty list.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_dependents.py
"""What a destructive change will break, and what could not be checked.

"Are you sure?" is not a confirmation. An empty list reads as "nothing depends on
this" — so a list that could not be computed must not be empty, it must say so.
"""
import pytest

from app.chat.dependents import Dependents


def test_it_carries_items_and_gaps():
    d = Dependents("policy rls-7 on crm.customers")
    d.item("table", "crm.customers", "loses row filtering entirely")
    d.skipped("PII detection not checked: no query engine on this deployment")
    assert d.done() == {
        "subject": "policy rls-7 on crm.customers",
        "items": [{"kind": "table", "name": "crm.customers",
                   "effect": "loses row filtering entirely"}],
        "not_checked": ["PII detection not checked: no query engine on this deployment"],
    }


def test_an_untouched_list_still_has_every_key():
    assert Dependents("x").done() == {"subject": "x", "items": [], "not_checked": []}


def test_nothing_found_and_nothing_checked_are_different_states():
    """The distinction the card renders differently, and the reason this type exists."""
    found_nothing = Dependents("x").done()
    could_not_check = Dependents("x").skipped("catalog unavailable").done()
    assert found_nothing["items"] == could_not_check["items"] == []
    assert not found_nothing["not_checked"]
    assert could_not_check["not_checked"]


def test_items_keep_the_order_they_were_added():
    d = Dependents("x")
    d.item("role", "viewer", "gains access")
    d.item("role", "analyst", "gains access")
    assert [i["name"] for i in d.done()["items"]] == ["viewer", "analyst"]


def test_kind_and_name_are_required_to_be_non_empty():
    """A blank row in a blast-radius list is worse than no row."""
    with pytest.raises(ValueError):
        Dependents("x").item("", "crm.customers", "effect")
    with pytest.raises(ValueError):
        Dependents("x").item("table", "", "effect")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_dependents.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.dependents'`.

- [ ] **Step 3: Write it**

```python
# backend/app/chat/dependents.py
"""What a destructive change will break.

Same split as app/chat/diagnosis.py, for the same reason: `items` are what was found,
`not_checked` is what was out of reach. An empty `items` with an empty `not_checked`
means "nothing depends on this" and is a claim. An empty `items` with a populated
`not_checked` means "I could not tell", which is a different card and a different
decision for the person reading it.
"""
from typing import Any, Dict, List


class Dependents:
    def __init__(self, subject: str) -> None:
        self.subject = subject
        self._items: List[dict] = []
        self._not_checked: List[str] = []

    def item(self, kind: str, name: str, effect: str) -> "Dependents":
        if not (kind or "").strip() or not (name or "").strip():
            raise ValueError("a dependent needs both a kind and a name")
        self._items.append({"kind": kind, "name": name, "effect": effect})
        return self

    def skipped(self, reason: str) -> "Dependents":
        self._not_checked.append(reason)
        return self

    def done(self) -> Dict[str, Any]:
        return {"subject": self.subject, "items": list(self._items),
                "not_checked": list(self._not_checked)}
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_dependents.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/dependents.py backend/tests/test_chat_dependents.py
git commit -m "feat(assistant): the shape of a blast-radius list, including its gaps"
```

---
## Task 3: The destructive branch in propose

**Files:**
- Modify: `backend/app/chat/actions.py` (add `target_field` to `Action`)
- Modify: `backend/app/chat/gate.py` (`propose`)
- Modify: `backend/app/api/chat_routes.py` (pass the user's turns)
- Test: `backend/tests/test_chat_destructive_gate.py`

**Interfaces:**
- Consumes: `named_by_user(target, turns)` from `app.chat.naming`; `Dependents` from `app.chat.dependents`.
- Produces: `Action.target_field: Optional[str]`; `propose(..., turns=None, dependents=None)` where `dependents` is an optional `(params, user) -> dict` callable; a destructive invocation's `preview` carries `{"target", "dependents", "named_by_user", ...}`.

No destructive action is registered yet. The gate is the part that must be right, and it is testable with a fabricated action before any real one exists.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_destructive_gate.py
"""The gate a destructive action passes through, tested without one existing.

A destructive proposal is refused before a card is ever rendered when the user did
not name the target. That is the order that matters: the model must not be able to
put a confirmation dialog in front of someone for a target they never mentioned,
because a dialog is an invitation to click.
"""
import asyncio

import pytest

from app.chat import gate
from app.chat.actions import Action, ActionKind, _Strict
from app.chat.gate import ActionRefused


def _run(c):
    return asyncio.run(c)


class _Target(_Strict):
    name: str


DROP = Action("test.drop_thing", "Drop thing", "Drops a thing.", ("*",),
              "governance:write", ActionKind.DESTRUCTIVE, _Target,
              target_field="name")


class _Store:
    def __init__(self):
        self.audits = []
        self.created = None

    async def record_audit(self, event, user_id, user_email, details):
        self.audits.append((event, details))

    async def create(self, **fields):
        self.created = fields
        return {"id": "inv-1", **fields}


USER = {"id": "u1", "permissions": ["governance:write"]}


def _propose(store, turns, **kw):
    return _run(gate.propose(
        DROP.id, {"name": "crm.customers"}, user=USER, page="*", store=store,
        turns=turns, **kw))


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    monkeypatch.setitem(gate.REGISTRY, DROP.id, DROP)
    monkeypatch.setattr(gate, "capability_on", lambda key: True)


def test_a_target_the_user_named_reaches_the_card():
    store = _Store()
    inv = _propose(store, [{"role": "user", "content": "drop crm.customers"}])
    assert inv["status"] == "proposed"
    assert inv["preview"]["target"] == "crm.customers"
    assert inv["preview"]["named_by_user"]["turn_index"] == 0


def test_a_target_only_the_assistant_named_is_refused_before_any_card():
    store = _Store()
    with pytest.raises(ActionRefused):
        _propose(store, [
            {"role": "user", "content": "clean up anything unused"},
            {"role": "assistant", "content": "crm.customers looks unused"},
        ])
    assert store.created is None, "no invocation may be recorded for a refused proposal"


def test_the_refusal_is_audited_with_its_reason():
    store = _Store()
    with pytest.raises(ActionRefused):
        _propose(store, [{"role": "user", "content": "tidy up"}])
    events = [d for e, d in store.audits if e == "chat_action_refused"]
    assert events and events[-1]["reason"] == "target_not_named"


def test_no_turns_at_all_refuses_rather_than_waves_through():
    """Fail closed: a caller that sent no history has proved nothing."""
    store = _Store()
    with pytest.raises(ActionRefused):
        _propose(store, [])


def test_dependents_are_computed_server_side_and_stored():
    store = _Store()

    def _deps(params, user):
        from app.chat.dependents import Dependents
        return Dependents(params["name"]).item("table", params["name"], "unfiltered").done()

    inv = _propose(store, [{"role": "user", "content": "drop crm.customers"}],
                   dependents=_deps)
    assert inv["preview"]["dependents"]["items"][0]["name"] == "crm.customers"


def test_a_destructive_action_never_executes_at_propose_time():
    """READ executes immediately; everything else waits. A destructive one waits
    hardest."""
    store = _Store()
    ran = []
    inv = _propose(store, [{"role": "user", "content": "drop crm.customers"}],
                   executor=lambda p, u: ran.append(p))
    assert ran == []
    assert inv["status"] == "proposed"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_destructive_gate.py -q`
Expected: FAIL — `Action.__init__() got an unexpected keyword argument 'target_field'`.

- [ ] **Step 3: Add `target_field` to `Action`**

In `backend/app/chat/actions.py`, add to the dataclass after `capability`:

```python
    # For a destructive action, the params field holding the thing being changed.
    # The gate reads the canonical target from here rather than from anything the
    # model wrote in prose, and it is what the user must type back.
    target_field: Optional[str] = None
```

- [ ] **Step 4: Add the destructive branch to `propose`**

In `backend/app/chat/gate.py`, import at the top:

```python
from app.chat.naming import named_by_user
```

Give `propose` two more keyword-only parameters, `turns: Optional[Sequence[Mapping]] = None` and `dependents: Optional[Callable] = None`, and insert this block after `clean = validate_params(action, params)` succeeds and before the preview is computed:

```python
    destructive_fields = {}
    if action.kind is ActionKind.DESTRUCTIVE:
        target = str(clean.get(action.target_field or "") or "")
        evidence = named_by_user(target, turns or ())
        if not evidence:
            # Refused before an invocation exists: a confirmation dialog is an
            # invitation to click, and the model must not be able to raise one for a
            # target the person never mentioned. See design §4 and §5.
            await _audit(store, "chat_action_refused", user,
                         action=action.id, stage="propose", reason="target_not_named",
                         target=target[:200])
            raise ActionRefused(
                f"You have not mentioned {target!r} in this conversation, so I will not "
                f"offer to change it. Name it and ask again.")
        destructive_fields = {
            "target": target,
            "named_by_user": evidence,
            "dependents": (await _maybe_await(dependents(clean, user))
                           if dependents is not None else None),
        }
```

Then merge those fields into the preview that is stored:

```python
    preview = None
    if action.kind is not ActionKind.READ and previewer is not None:
        preview = await _maybe_await(previewer(clean, user))
    if destructive_fields:
        preview = {**(preview or {}), **destructive_fields}
```

- [ ] **Step 5: Pass the user's turns from the route**

In `backend/app/api/chat_routes.py`, wherever `gate.propose(...)` is called, pass the conversation so far plus the message being handled:

```python
        turns=[{"role": t.role, "content": t.content} for t in request.history]
              + [{"role": "user", "content": text}],
```

Use `text` — the PII-masked message — not `request.message`: it is what the rest of this turn already works from, and masking does not remove identifiers of the kind a target name uses.

- [ ] **Step 6: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_destructive_gate.py tests/test_chat_gate.py tests/test_chat_actions.py tests/test_chat_capability_gate.py -q`
Expected: PASS. The existing gate tests are untouched — no registered action is destructive yet.

- [ ] **Step 7: Commit**

```bash
git add backend/app/chat/actions.py backend/app/chat/gate.py backend/app/api/chat_routes.py backend/tests/test_chat_destructive_gate.py
git commit -m "feat(assistant): refuse a destructive proposal for a target nobody named

A confirmation dialog is an invitation to click, so the check runs before one is
rendered rather than after. The evidence is the user's own turns; the target is
read from validated params, never from the model's prose.

No action is destructive yet — the gate is the part that must be right, and it
is testable before anything registers behind it."
```

---

## Task 4: Typing the target at approval

**Files:**
- Modify: `backend/app/chat/gate.py` (`approve`)
- Modify: `backend/app/api/chat_routes.py` (the approve route)
- Test: `backend/tests/test_chat_typed_target.py`

**Interfaces:**
- Consumes: `normalise` from `app.chat.naming`; the `preview["target"]` written by Task 3.
- Produces: `approve(invocation_id, *, user, store, executor=None, typed_target=None)`; the approve route accepts an optional JSON body `{"typed_target": "..."}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_typed_target.py
"""The second line: the person types the name of the thing they are changing.

The first line is Task 3 — the model cannot raise a dialog for an unnamed target.
This one is against the person clicking through a dialog they did raise.
"""
import asyncio

import pytest

from app.chat import gate
from app.chat.actions import Action, ActionKind, _Strict
from app.chat.gate import ActionRefused


def _run(c):
    return asyncio.run(c)


class _Target(_Strict):
    name: str


DROP = Action("test.drop_thing", "Drop thing", "Drops a thing.", ("*",),
              "governance:write", ActionKind.DESTRUCTIVE, _Target,
              target_field="name")

INVOCATION = {
    "id": "inv-1", "action_id": DROP.id, "user_id": "u1", "status": "proposed",
    "params": {"name": "crm.customers"},
    "preview": {"target": "crm.customers", "named_by_user": {"turn_index": 0}},
}


class _Store:
    def __init__(self):
        self.audits = []
        self.status = None

    async def record_audit(self, event, user_id, user_email, details):
        self.audits.append((event, details))

    async def get(self, invocation_id):
        return dict(INVOCATION)

    async def set_status(self, invocation_id, status, **kw):
        self.status = status
        return {**INVOCATION, "status": status}


USER = {"id": "u1", "permissions": ["governance:write"]}


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    monkeypatch.setitem(gate.REGISTRY, DROP.id, DROP)
    monkeypatch.setattr(gate, "capability_on", lambda key: True)


def test_the_exact_name_executes():
    store, ran = _Store(), []
    _run(gate.approve("inv-1", user=USER, store=store,
                      executor=lambda p, u: ran.append(p) or {"ok": True},
                      typed_target="crm.customers"))
    assert ran == [{"name": "crm.customers"}]


def test_a_different_name_does_not_execute():
    store, ran = _Store(), []
    with pytest.raises(ActionRefused):
        _run(gate.approve("inv-1", user=USER, store=store,
                          executor=lambda p, u: ran.append(p),
                          typed_target="crm.orders"))
    assert ran == []


def test_no_typed_name_at_all_does_not_execute():
    """Omitting the field is not the same as matching it."""
    store, ran = _Store(), []
    with pytest.raises(ActionRefused):
        _run(gate.approve("inv-1", user=USER, store=store,
                          executor=lambda p, u: ran.append(p)))
    assert ran == []


def test_case_and_surrounding_quotes_are_forgiven():
    """The point is intent, not transcription. Copying the name out of the card and
    picking up a backtick must not be a failure."""
    store, ran = _Store(), []
    _run(gate.approve("inv-1", user=USER, store=store,
                      executor=lambda p, u: ran.append(p) or {"ok": True},
                      typed_target=' "CRM.Customers" '))
    assert ran


def test_the_mismatch_is_audited():
    store = _Store()
    with pytest.raises(ActionRefused):
        _run(gate.approve("inv-1", user=USER, store=store, typed_target="wrong"))
    assert any(d.get("reason") == "typed_target_mismatch"
               for e, d in store.audits if e == "chat_action_refused")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_typed_target.py -q`
Expected: FAIL — `approve() got an unexpected keyword argument 'typed_target'`.

- [ ] **Step 3: Add the comparison to `approve`**

In `backend/app/chat/gate.py`, import `normalise` alongside `named_by_user`, add `typed_target: Optional[str] = None` to `approve`'s keyword-only parameters, and insert this immediately after the invocation is loaded and its owner checked, before anything executes:

```python
    if action.kind is ActionKind.DESTRUCTIVE:
        expected = ((invocation.get("preview") or {}).get("target")) or ""
        if not expected or normalise(typed_target or "") != normalise(expected):
            await _audit(store, "chat_action_refused", user,
                         action=action.id, stage="approve",
                         reason="typed_target_mismatch", invocation=invocation_id)
            raise ActionRefused(
                f"To confirm, type the name exactly: {expected}")
```

An invocation whose stored preview carries no target fails this too — a destructive record that lost its target is not one to execute on a guess.

- [ ] **Step 4: Accept it on the route**

In `backend/app/api/chat_routes.py`, give the approve route an optional body and pass it through:

```python
class ApproveRequest(BaseModel):
    model_config = {"extra": "forbid"}
    typed_target: Optional[str] = None


@router.post("/chat/actions/{invocation_id}/approve")
async def approve_action(invocation_id: str, body: Optional[ApproveRequest] = None,
                         user: dict = Depends(require_human)):
    ...
    return await gate.approve(invocation_id, user=user, store=await _store(user),
                              executor=..., typed_target=(body.typed_target if body else None))
```

Keep every other argument exactly as it is today. The body is optional so a mutate approval, which sends none, still works.

- [ ] **Step 5: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_typed_target.py tests/test_chat_destructive_gate.py tests/test_chat_user_proposal.py tests/test_chat_human_only.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat/gate.py backend/app/api/chat_routes.py backend/tests/test_chat_typed_target.py
git commit -m "feat(assistant): a destructive approval requires typing the target

Compared against the name the server stored at propose time, not one the client
sends alongside. Case and quoting are forgiven because the point is intent, not
transcription; anything else is refused and audited."
```

---
## Task 5: The destructive card

**Files:**
- Create: `frontend/components/chat/destructive-card.tsx`
- Modify: `frontend/components/chat/assistant-panel.tsx` (render it when the pending invocation carries a target)
- Test: `frontend/lib/destructive-card-state.test.ts`
- Create: `frontend/lib/destructive-card-state.ts`

**Interfaces:**
- Consumes: the pending invocation's `preview`, which carries `target`, `dependents` and `named_by_user` from Task 3.
- Produces: `canConfirm(typed: string, target: string): boolean` in `frontend/lib/destructive-card-state.ts`, and `<DestructiveCard pending onApprove onDismiss />`.

The confirm rule lives in a plain module because that is what this repo can test — its frontend tests are `node:test` over `lib/`, with no component harness. Put the logic there and keep the component thin enough that reading it is enough.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/lib/destructive-card-state.test.ts
/** When the confirm button may be pressed.
 *
 *  The server checks this again — this is not the gate, it is the part that stops a
 *  person submitting a mismatch and being told off for it. The two must agree, so
 *  the forgiveness here matches the server's: case and surrounding quotes.
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { canConfirm } from "./destructive-card-state.ts"

test("the exact name confirms", () => {
  assert.equal(canConfirm("crm.customers", "crm.customers"), true)
})

test("a different name does not", () => {
  assert.equal(canConfirm("crm.orders", "crm.customers"), false)
})

test("nothing typed does not", () => {
  assert.equal(canConfirm("", "crm.customers"), false)
  assert.equal(canConfirm("   ", "crm.customers"), false)
})

test("case and surrounding quotes are forgiven, exactly as the server forgives them", () => {
  for (const typed of [' "CRM.Customers" ', "`crm.customers`", "CRM.CUSTOMERS"]) {
    assert.equal(canConfirm(typed, "crm.customers"), true, typed)
  }
})

test("a partial name does not confirm", () => {
  assert.equal(canConfirm("customers", "crm.customers"), false)
})

test("an absent target never confirms, whatever is typed", () => {
  // A card with no target is a card the server will refuse. Do not let the button
  // look pressable.
  assert.equal(canConfirm("anything", ""), false)
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npm test`
Expected: FAIL — cannot resolve `./destructive-card-state.ts`.

- [ ] **Step 3: Write the module**

```typescript
// frontend/lib/destructive-card-state.ts
/** Whether the typed name matches the target the server is expecting.
 *
 *  The server checks this again at approval and refuses a mismatch; this only decides
 *  whether the button is pressable. Both sides forgive the same two things — case, and
 *  the quotes people pick up when copying an identifier — because the point is intent,
 *  not transcription.
 *
 *  Partial names do not count. "customers" is enough for the server to accept that you
 *  *named* crm.customers in conversation, but not to confirm that you mean to change it.
 */
export function canConfirm(typed: string, target: string): boolean {
  const clean = (s: string) => (s ?? "").trim().replace(/^["'`]+|["'`]+$/g, "").trim().toLowerCase()
  const wanted = clean(target)
  return wanted.length > 0 && clean(typed) === wanted
}
```

- [ ] **Step 4: Write the card**

```tsx
// frontend/components/chat/destructive-card.tsx
"use client"

import { useState } from "react"
import { AlertTriangle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { canConfirm } from "@/lib/destructive-card-state"

type Dependent = { kind: string; name: string; effect: string }
type Pending = {
  id: string
  label: string
  preview?: {
    target?: string
    dependents?: { items?: Dependent[]; not_checked?: string[] } | null
  }
}

/** The card for a change that cannot be undone from what the product still holds.
 *
 *  Three things a plain approval does not do: it names what else changes, it makes the
 *  person type the target, and it says plainly when the blast radius could not be
 *  worked out. That last one matters most — an empty list reads as "nothing else is
 *  affected", so a list that was never computed must not look like one.
 */
export function DestructiveCard({ pending, onApprove, onDismiss, busy }: {
  pending: Pending
  onApprove: (typedTarget: string) => void
  onDismiss: () => void
  busy: boolean
}) {
  const [typed, setTyped] = useState("")
  const target = pending.preview?.target ?? ""
  const items = pending.preview?.dependents?.items ?? []
  const notChecked = pending.preview?.dependents?.not_checked ?? []

  return (
    <div className="rounded-lg border border-[var(--dp-bad)]/40 bg-[var(--dp-bad)]/5 p-3">
      <p className="flex items-center gap-1.5 text-xs font-medium">
        <AlertTriangle className="h-3.5 w-3.5 text-[var(--dp-bad)]" />
        {pending.label}
      </p>

      {items.length > 0 && (
        <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
          {items.map((d, i) => (
            <li key={i}><span className="font-medium">{d.name}</span> — {d.effect}</li>
          ))}
        </ul>
      )}
      {items.length === 0 && notChecked.length === 0 && (
        <p className="mt-2 text-[11px] text-muted-foreground">Nothing else depends on this.</p>
      )}
      {notChecked.length > 0 && (
        <ul className="mt-2 space-y-1 text-[11px] text-[var(--dp-warn)]">
          {notChecked.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}

      <label className="mt-3 block text-[11px] text-muted-foreground">
        Type <span className="font-mono font-medium text-foreground">{target}</span> to confirm
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          className="mt-1 w-full rounded-md border bg-background px-2 py-1 font-mono text-xs"
          autoComplete="off"
        />
      </label>

      <div className="mt-2.5 flex gap-2">
        <Button size="sm" className="h-7 text-xs" disabled={busy || !canConfirm(typed, target)}
                onClick={() => onApprove(typed)}>
          Confirm
        </Button>
        <Button size="sm" variant="ghost" className="h-7 text-xs" disabled={busy}
                onClick={onDismiss}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Render it from the panel**

In `frontend/components/chat/assistant-panel.tsx`, where the pending approval card is rendered today, branch on whether the invocation carries a target, and pass the typed value through to the approve call:

```tsx
{pending && (pending.preview?.target
  ? <DestructiveCard pending={pending} busy={busy}
                     onApprove={(typedTarget) => decide(true, typedTarget)}
                     onDismiss={() => decide(false)} />
  : /* the existing approve/dismiss card, unchanged */ null)}
```

and give the existing `decide` an optional second argument that becomes the request body:

```tsx
const res = await fetch(`/api/chat/actions/${pending.id}/${accept ? "approve" : "reject"}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(typedTarget ? { typed_target: typedTarget } : {}),
})
```

Leave the rest of that function alone.

- [ ] **Step 6: Verify**

Run: `cd frontend && npm test && npx tsc --noEmit -p tsconfig.json && npm run build`
Expected: tests pass, tsc clean, build succeeds. The build is the only one of the three that catches a dropped JSX tag.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/destructive-card-state.ts frontend/lib/destructive-card-state.test.ts frontend/components/chat/destructive-card.tsx frontend/components/chat/assistant-panel.tsx
git commit -m "feat(assistant): the card for a change that cannot be undone

Names what else changes, makes the person type the target, and says plainly when
the blast radius could not be computed — an empty list reads as 'nothing else is
affected', so one that was never computed must not look like one."
```

---

## Task 6: The five reversible changes

**Files:**
- Modify: `backend/app/chat/analysis/knowledge.py` (`set_refresh_schedule`, `add_member`, `remove_member`)
- Modify: `backend/app/chat/analysis/connectors.py` (`set_schedule`, `set_sync_mode`)
- Modify: `backend/tests/test_chat_executor_wiring.py` (one `_params_for` entry per new id)
- Test: `backend/tests/test_chat_reversible_actions.py`

**Interfaces:**
- Produces: `knowledge.set_refresh_schedule`, `knowledge.add_member`, `knowledge.remove_member`, `connectors.set_schedule`, `connectors.set_sync_mode` — all `ActionKind.CREATE` (the existing preview → approve card), `pages=("*",)`.

`ActionKind.CREATE` rather than a new `MUTATE` member: the enum already has `CREATE` and `MUTATE`, and the gate treats everything that is not `READ` and not `DESTRUCTIVE` identically. Use `MUTATE` for these five, since they edit existing state — that is what the member is for, and it has never been used.

**Read these handlers before writing the executors** — every one takes a Depends-defaulted `user`, and two take a pydantic body whose field names you must not guess:
- `app/api/ai_vectors.py`: `schedule_ingest(name, body: ScheduleRequest, user)`, `add_member(name, body: MemberGrant, user)`, and the member-removal route beside them.
- `app/api/connectors.py`: `set_schedule(connection_id, request: ScheduleRequest, user)` and `set_connection_sync_mode(connection_id, body: dict, user)`. Note the two `ScheduleRequest` classes are different types in different modules.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_reversible_actions.py
"""Configuration the assistant may change behind the ordinary approval card.

Every one of these is undoable from what is on screen: set the number back, flip the
switch back, re-add the member. That is the whole reason they do not need the
destructive gate — see the grading rule in the spec.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind

IDS = ["knowledge.set_refresh_schedule", "knowledge.add_member",
       "knowledge.remove_member", "connectors.set_schedule",
       "connectors.set_sync_mode"]


def _run(c):
    return asyncio.run(c)


@pytest.mark.parametrize("action_id", IDS)
def test_each_is_a_mutate_not_a_read_and_not_destructive(action_id):
    action = REGISTRY[action_id]
    assert action.kind is ActionKind.MUTATE, (
        f"{action_id} changes state, so it must not execute without approval")
    assert action.target_field is None, (
        f"{action_id} is reversible; a typed target would be friction with no payer")


@pytest.mark.parametrize("action_id", IDS)
def test_each_has_a_previewer(action_id):
    """A card that says nothing about what will change is a card nobody reads."""
    from app.chat.analysis import PREVIEWERS
    assert action_id in PREVIEWERS


def test_the_knowledge_actions_pass_the_caller_through(monkeypatch):
    """These handlers take `user` as a Depends default. Called without it, the Depends
    object arrives as the user and the collection ACL is asked about the wrong thing."""
    from app.chat.analysis import knowledge as mod
    seen = {}

    async def _fake(name, body, user=None):
        seen.update(name=name, user=user)
        return {"ok": True}

    monkeypatch.setattr("app.api.ai_vectors.add_member", _fake)
    user = {"id": "u1"}
    _run(mod.add_member_action({"collection": "handbook", "email": "a@b.c",
                                "role": "viewer"}, user))
    assert seen == {"name": "handbook", "user": user}


def test_the_connector_actions_pass_the_caller_through(monkeypatch):
    from app.chat.analysis import connectors as mod
    seen = {}

    async def _fake(connection_id, request=None, user=None):
        seen.update(connection_id=connection_id, user=user)
        return {"ok": True}

    monkeypatch.setattr("app.api.connectors.set_schedule", _fake)
    user = {"id": "u1"}
    _run(mod.set_schedule_action({"connection_id": "c1", "cron": "0 2 * * *"}, user))
    assert seen == {"connection_id": "c1", "user": user}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_reversible_actions.py -q`
Expected: FAIL — `KeyError: 'knowledge.set_refresh_schedule'`.

- [ ] **Step 3: Add the three knowledge actions**

Executors named `*_action` for the reason the module already documents: two things called `add_member` in one file is how the wrong one gets called. Build each body from the real pydantic model — read `ScheduleRequest` and `MemberGrant` in `app/api/ai_vectors.py` and construct them, do not pass a bare dict.

Each gets a previewer returning what the card should say — for `add_member`, who is being given what on which collection; for `set_refresh_schedule`, the interval and whether it is being turned on or off.

Register in that module's `ACTIONS`, `EXECUTORS`, `RESOLVERS` and `PREVIEWERS`, with `ActionKind.MUTATE`, `permission="knowledge:write"`, `pages=("*",)`, and no capability.

- [ ] **Step 4: Add the two connector actions**

Same shape, `permission="connector:write"`, `capability="connectors"`. `set_connection_sync_mode` takes `body: dict` rather than a model — pass the exact keys the handler reads, which you must confirm by reading it.

- [ ] **Step 5: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_reversible_actions.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat/analysis/knowledge.py backend/app/chat/analysis/connectors.py backend/tests/test_chat_reversible_actions.py backend/tests/test_chat_executor_wiring.py
git commit -m "feat(assistant): change the settings you can change back

Refresh schedules, collection membership, connector schedule and sync mode. All
five are undoable from what is on the screen, so they use the approval card that
already exists rather than the destructive gate."
```

---
## Task 7: Creating a policy

**Files:**
- Modify: `backend/app/chat/analysis/governance.py`
- Modify: `backend/tests/test_chat_executor_wiring.py`
- Test: `backend/tests/test_chat_policy_create.py`

**Interfaces:**
- Produces: `governance.create_rls_policy`, `governance.create_masking_policy` — `ActionKind.MUTATE`, `governance:write`, no capability, no `target_field`.

Creating a policy is a mutate under the grading rule: you undo it by deleting it, and deleting is the destructive one. **Read `RlsPolicyIn` and `MaskPolicyIn` in `app/api/governance.py` and construct them; do not pass dicts.** Both handlers take `user: Optional[dict] = Depends(_get_current_user)` — pass it.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_policy_create.py
"""Creating a row filter or a column mask, behind the ordinary approval card.

A policy that is too tight is an inconvenience someone reports. A policy that is
too loose is a leak nobody reports, so the preview has to say who it will apply to
before anyone approves it.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind


def _run(c):
    return asyncio.run(c)


@pytest.mark.parametrize("action_id",
                         ["governance.create_rls_policy", "governance.create_masking_policy"])
def test_creating_is_a_mutate(action_id):
    action = REGISTRY[action_id]
    assert action.kind is ActionKind.MUTATE
    assert action.permission == "governance:write"
    assert action.target_field is None


def test_the_preview_says_which_table_and_which_roles(monkeypatch):
    from app.chat.analysis import governance as mod
    card = _run(mod.preview_create_rls_policy(
        {"table": "crm.customers", "roles": ["analyst"], "expression": "region = 'EU'"},
        {"id": "u1"}))
    rendered = repr(card)
    assert "crm.customers" in rendered and "analyst" in rendered


def test_the_executor_passes_the_caller(monkeypatch):
    from app.chat.analysis import governance as mod
    seen = {}

    async def _fake(body, user=None):
        seen["user"] = user
        return {"id": "rls-1"}

    monkeypatch.setattr("app.api.governance.create_rls_policy", _fake)
    user = {"id": "u1"}
    _run(mod.create_rls_policy_action(
        {"table": "crm.customers", "roles": ["analyst"], "expression": "region = 'EU'"},
        user))
    assert seen["user"] is user
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_policy_create.py -q`
Expected: FAIL — `KeyError: 'governance.create_rls_policy'`.

- [ ] **Step 3: Implement both, with previewers**

Executors `create_rls_policy_action` and `create_masking_policy_action`; previewers `preview_create_rls_policy` and `preview_create_masking_policy` returning the table, the roles and the expression or masking rule, so the card says what the policy will do rather than that a policy will exist. Register with `ActionKind.MUTATE`.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_policy_create.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/governance.py backend/tests/test_chat_policy_create.py backend/tests/test_chat_executor_wiring.py
git commit -m "feat(assistant): create a row filter or a column mask"
```

---

## Task 8: Deleting a policy, and what that breaks

**Files:**
- Modify: `backend/app/chat/analysis/governance.py`
- Test: `backend/tests/test_chat_policy_delete.py`

**Interfaces:**
- Consumes: `Dependents` from `app.chat.dependents`; the destructive branch from Task 3.
- Produces: `governance.delete_rls_policy`, `governance.delete_masking_policy` — `ActionKind.DESTRUCTIVE`, `governance:write`, `target_field="policy_id"`, each with a `dependents` callable registered in a new module-level `DEPENDENTS` dict exported alongside `PREVIEWERS`.

The dependents computation is the point of this task. Deleting a row filter is not "one row disappears from a table of policies" — it is "these roles can now see rows they could not see before", and that sentence is what the person approving needs.

**Read the policy store before writing this.** `/governance/rls/coverage` already answers "which tables have a policy"; use the same source rather than inventing a second one, and confirm what a policy row actually contains.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_policy_delete.py
"""Deleting a policy, and saying what stops being protected.

"Are you sure?" is not a confirmation. The card has to say which table loses
filtering and who can see rows afterwards that they cannot see now.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind


def _run(c):
    return asyncio.run(c)


@pytest.mark.parametrize("action_id",
                         ["governance.delete_rls_policy", "governance.delete_masking_policy"])
def test_deleting_is_destructive_and_names_its_target_field(action_id):
    action = REGISTRY[action_id]
    assert action.kind is ActionKind.DESTRUCTIVE
    assert action.target_field == "policy_id"


def test_the_last_policy_on_a_table_reports_that_the_table_becomes_unfiltered(monkeypatch):
    from app.chat.analysis import governance as mod
    monkeypatch.setattr(mod, "_policies_for_table",
                        lambda table: [{"id": "rls-7", "roles": ["analyst"]}])
    monkeypatch.setattr(mod, "_policy_by_id",
                        lambda pid: {"id": "rls-7", "table": "crm.customers",
                                     "roles": ["analyst"]})
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-7"}, {"id": "u1"}))
    effects = " ".join(i["effect"] for i in out["items"])
    assert "crm.customers" in repr(out)
    assert "no row filtering" in effects or "unfiltered" in effects


def test_another_policy_still_covering_the_table_is_said_so(monkeypatch):
    """Deleting one of two is a different decision from deleting the only one."""
    from app.chat.analysis import governance as mod
    monkeypatch.setattr(mod, "_policies_for_table",
                        lambda table: [{"id": "rls-7", "roles": ["analyst"]},
                                       {"id": "rls-8", "roles": ["viewer"]}])
    monkeypatch.setattr(mod, "_policy_by_id",
                        lambda pid: {"id": "rls-7", "table": "crm.customers",
                                     "roles": ["analyst"]})
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-7"}, {"id": "u1"}))
    assert "rls-8" in repr(out)


def test_a_policy_store_that_cannot_be_read_is_not_checked_not_empty(monkeypatch):
    """An empty items list reads as 'nothing depends on this'."""
    from app.chat.analysis import governance as mod

    def _boom(_):
        raise RuntimeError("policy store unavailable")

    monkeypatch.setattr(mod, "_policy_by_id", _boom)
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-7"}, {"id": "u1"}))
    assert out["items"] == []
    assert out["not_checked"], "an uncomputed blast radius must say so"


def test_masking_delete_names_the_columns_that_stop_being_masked(monkeypatch):
    from app.chat.analysis import governance as mod
    monkeypatch.setattr(mod, "_mask_policy_by_id",
                        lambda pid: {"id": "m-1", "table": "crm.customers",
                                     "column": "email", "rule": "partial"})
    out = _run(mod.dependents_delete_masking_policy({"policy_id": "m-1"}, {"id": "u1"}))
    assert "email" in repr(out)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_policy_delete.py -q`
Expected: FAIL — `KeyError: 'governance.delete_rls_policy'`.

- [ ] **Step 3: Implement the dependents helpers and the two actions**

Write `_policy_by_id`, `_policies_for_table` and `_mask_policy_by_id` as thin readers over the policy store the coverage endpoint already uses, and wrap every one of them in the executor with a `try/except` that calls `.skipped(...)` — an unreachable store must produce `not_checked`, never an empty list. Register `dependents_delete_rls_policy` and `dependents_delete_masking_policy` in a `DEPENDENTS` dict, and export it from `app/chat/analysis/__init__.py` the same way `PREVIEWERS` is, so the route can pass it to `gate.propose`.

- [ ] **Step 4: Wire `DEPENDENTS` through the route**

In `backend/app/api/chat_routes.py`, pass `dependents=DEPENDENTS.get(action_id)` to `gate.propose` alongside the executor and previewer it already passes.

- [ ] **Step 5: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_policy_delete.py tests/test_chat_destructive_gate.py tests/test_chat_analysis_assembly.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat/analysis/governance.py backend/app/chat/analysis/__init__.py backend/app/api/chat_routes.py backend/tests/test_chat_policy_delete.py
git commit -m "feat(assistant): delete a policy, having said what stops being protected

Which table loses filtering, whether another policy still covers it, and which
roles can see rows afterwards. A store that cannot be read produces 'not
checked' rather than an empty list that reads as 'nothing depends on this'."
```

---

## Task 9: Model configuration, without the credentials

**Files:**
- Create: `backend/app/chat/analysis/settings.py`
- Modify: `backend/app/chat/analysis/__init__.py`
- Test: `backend/tests/test_chat_settings_action.py`

**Interfaces:**
- Produces: `settings.set_model_config` — `ActionKind.DESTRUCTIVE`, `settings:write`, `target_field="key"`, with `ALLOWED_KEYS` derived as `set(AI_ENV_MAP) - SENSITIVE_KEYS`.

Destructive under the grading rule: the previous value may be a secret this product will not show, and every later model call changes cost and destination.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_settings_action.py
"""Changing model configuration, with credentials out of reach.

The settings body is a dictionary by nature, so `extra="forbid"` on a params model
does not reach it. The allowlist is checked again at execution, and it is derived
rather than written so that a credential added later is excluded without anyone
remembering to exclude it.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind
from app.chat.analysis import settings as mod


def _run(c):
    return asyncio.run(c)


def test_it_is_destructive_and_targets_the_key():
    action = REGISTRY["settings.set_model_config"]
    assert action.kind is ActionKind.DESTRUCTIVE
    assert action.target_field == "key"
    assert action.permission == "settings:write"


def test_the_allowlist_is_the_difference_of_two_existing_sets():
    """Derived, not written: a credential added to SENSITIVE_KEYS later is excluded
    without anyone having to remember this file exists."""
    from app.api.system_settings import AI_ENV_MAP, SENSITIVE_KEYS
    assert mod.ALLOWED_KEYS == set(AI_ENV_MAP) - set(SENSITIVE_KEYS)
    assert mod.ALLOWED_KEYS == {"ai.provider", "ai.litellm_url", "ai.litellm_model"}


@pytest.mark.parametrize("key", ["ai.aws_access_key_id", "ai.aws_secret_access_key"])
def test_a_credential_key_is_refused_at_execution(key, monkeypatch):
    """Not merely absent from the schema — refused by the code that would write it."""
    called = []
    monkeypatch.setattr("app.api.system_settings.update_system_settings",
                        lambda body: called.append(body))
    with pytest.raises(ValueError):
        _run(mod.set_model_config({"key": key, "value": "AKIA..."}, {"id": "u1"}))
    assert called == []


def test_a_key_nobody_has_heard_of_is_refused(monkeypatch):
    called = []
    monkeypatch.setattr("app.api.system_settings.update_system_settings",
                        lambda body: called.append(body))
    with pytest.raises(ValueError):
        _run(mod.set_model_config({"key": "ai.something_new", "value": "x"}, {"id": "u1"}))
    assert called == []


def test_an_allowed_key_is_written(monkeypatch):
    seen = {}

    async def _fake(body):
        seen["body"] = body
        return {"ok": True}

    monkeypatch.setattr("app.api.system_settings.update_system_settings", _fake)
    _run(mod.set_model_config({"key": "ai.litellm_model", "value": "claude-sonnet-5"},
                              {"id": "u1"}))
    assert seen["body"].settings == {"ai.litellm_model": "claude-sonnet-5"}


def test_changing_the_embedding_model_lists_the_collections_it_will_strand(monkeypatch):
    """The reason this action computes dependents at all: a collection embedded with
    one model and queried through another loses retrieval quality with nothing logged.
    knowledge.diagnose_collection finds that afterwards; this shows it before."""
    monkeypatch.setattr(mod, "_collections_by_embed_model",
                        lambda: [{"name": "handbook", "embed_model": "titan-v1"},
                                 {"name": "tickets", "embed_model": "titan-v2"}])
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.litellm_model", "value": "titan-v2"}, {"id": "u1"}))
    names = repr(out)
    assert "handbook" in names and "titan-v1" in names


def test_collections_that_cannot_be_listed_are_not_checked(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "_collections_by_embed_model", _boom)
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.litellm_model", "value": "titan-v2"}, {"id": "u1"}))
    assert out["items"] == [] and out["not_checked"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_settings_action.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.analysis.settings'`.

- [ ] **Step 3: Write the module**

Derive `ALLOWED_KEYS` from `AI_ENV_MAP` and `SENSITIVE_KEYS`, refuse anything outside it with a `ValueError` **before** constructing the patch, build a real `SettingsPatch` rather than a dict, and compute dependents by reading `ai_collections.name, embed_model` and listing the ones whose model will no longer match. Wrap that read in `try/except` and `.skipped(...)`.

Add `settings` to `_MODULES` and register its `DEPENDENTS` entry.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_settings_action.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/settings.py backend/app/chat/analysis/__init__.py backend/tests/test_chat_settings_action.py
git commit -m "feat(assistant): change model configuration, never a credential

The allowlist is AI_ENV_MAP minus SENSITIVE_KEYS, so a credential added later is
excluded without anyone remembering this file exists, and it is enforced at
execution because the settings body is a dictionary by nature.

Changing the embedding model lists the collections it strands — the silent
retrieval loss diagnose_collection was built to find after the fact."
```

---
## Task 10: Granting a role

**Files:**
- Create: `backend/app/chat/analysis/users.py`
- Modify: `backend/app/chat/analysis/__init__.py`
- Test: `backend/tests/test_chat_grant_role.py`

**Interfaces:**
- Produces: `users.grant_role` — `ActionKind.DESTRUCTIVE`, `user:manage`, `target_field="email"`, with `dependents_grant_role` naming the permission difference.
- Consumes: `ROLE_PERMISSIONS`, `ASSIGNABLE_ROLES`, `permissions_for` from `app.permissions`; `update_user` in `app/api/auth.py`, which applies a role when `body["role"] in ASSIGNABLE_ROLES`.

This is the action with the largest blast radius in the whole feature, so its three constraints are enforced **at execution**, where a forged proposal still meets them — not in the schema, which only shapes what the model may propose.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_grant_role.py
"""Granting a role, with the three things that must never be possible.

Permission changes are the one category where a mistake grants the mistake-maker
more room to make mistakes. The constraints live at execution because that is
where a forged proposal arrives.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind
from app.chat.analysis import users as mod


def _run(c):
    return asyncio.run(c)


from app.permissions import ALL_PERMISSIONS

ADMIN = {"id": "u-admin", "email": "admin@example.com",
         "permissions": sorted(ALL_PERMISSIONS)}
LIMITED = {"id": "u-eng", "email": "eng@example.com",
           "permissions": ["user:manage", "catalog:read", "knowledge:read"]}


def test_it_is_destructive_and_targets_the_person():
    action = REGISTRY["users.grant_role"]
    assert action.kind is ActionKind.DESTRUCTIVE
    assert action.target_field == "email"
    assert action.permission == "user:manage"


def test_a_grant_within_the_callers_own_permissions_is_allowed(monkeypatch):
    seen = {}

    async def _fake(user_id, body, admin=None):
        seen.update(user_id=user_id, body=body)
        return {"ok": True}

    monkeypatch.setattr("app.api.auth.update_user", _fake)
    monkeypatch.setattr(mod, "_user_by_email",
                        lambda e: {"id": "u-2", "email": e, "role": "viewer"})
    _run(mod.grant_role({"email": "someone@example.com", "role": "business_analyst"},
                        ADMIN))
    assert seen["body"]["role"] == "business_analyst"


def test_a_grant_beyond_the_callers_own_permissions_is_refused(monkeypatch):
    """You cannot hand out what you do not hold — the rule that stops the assistant
    becoming a way around the permission matrix."""
    monkeypatch.setattr(mod, "_user_by_email",
                        lambda e: {"id": "u-2", "email": e, "role": "viewer"})
    called = []
    monkeypatch.setattr("app.api.auth.update_user",
                        lambda *a, **k: called.append(a))
    with pytest.raises(PermissionError):
        _run(mod.grant_role({"email": "someone@example.com", "role": "admin"}, LIMITED))
    assert called == []


def test_user_manage_is_never_grantable(monkeypatch):
    """An assistant that can make administrators is a different product."""
    monkeypatch.setattr(mod, "_user_by_email",
                        lambda e: {"id": "u-2", "email": e, "role": "viewer"})
    called = []
    monkeypatch.setattr("app.api.auth.update_user", lambda *a, **k: called.append(a))
    with pytest.raises(PermissionError):
        _run(mod.grant_role({"email": "someone@example.com", "role": "admin"}, ADMIN))
    assert called == []


def test_nobody_may_change_their_own_role(monkeypatch):
    """Costs an admin nothing — the UI still does it — and closes the path injected
    content aims at first."""
    monkeypatch.setattr(mod, "_user_by_email",
                        lambda e: {"id": ADMIN["id"], "email": e, "role": "viewer"})
    called = []
    monkeypatch.setattr("app.api.auth.update_user", lambda *a, **k: called.append(a))
    with pytest.raises(PermissionError):
        _run(mod.grant_role({"email": ADMIN["email"], "role": "data_engineer"}, ADMIN))
    assert called == []


def test_the_dependents_name_the_permissions_gained_not_the_role(monkeypatch):
    """"admin" tells the approver nothing they can weigh. The list of things this
    person will be able to do that they cannot do today does."""
    monkeypatch.setattr(mod, "_user_by_email",
                        lambda e: {"id": "u-2", "email": e, "role": "viewer"})
    out = _run(mod.dependents_grant_role(
        {"email": "someone@example.com", "role": "data_engineer"}, ADMIN))
    rendered = repr(out)
    assert "connector:write" in rendered
    assert "viewer" in rendered or "data_engineer" in rendered


def test_an_unknown_person_is_refused_rather_than_created(monkeypatch):
    monkeypatch.setattr(mod, "_user_by_email", lambda e: None)
    with pytest.raises(ValueError):
        _run(mod.grant_role({"email": "nobody@example.com", "role": "viewer"}, ADMIN))


def test_a_user_that_cannot_be_looked_up_is_not_checked(monkeypatch):
    def _boom(_):
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "_user_by_email", _boom)
    out = _run(mod.dependents_grant_role(
        {"email": "someone@example.com", "role": "viewer"}, ADMIN))
    assert out["items"] == [] and out["not_checked"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_grant_role.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.analysis.users'`.

- [ ] **Step 3: Write the module**

Three checks in `grant_role`, each raising before `update_user` is reached:

```python
GRANTABLE = frozenset(ASSIGNABLE_ROLES) - {"admin"}


async def grant_role(params: dict, user: dict) -> dict:
    """Set someone's role, within three limits that hold even for an admin.

    They are enforced here rather than in the params schema because the schema only
    shapes what the model may propose; this is what a forged proposal meets.
    """
    from app.api.auth import update_user
    from app.permissions import ROLE_PERMISSIONS, permissions_for

    role = params["role"]
    if role not in GRANTABLE:
        # `admin` carries user:manage, and an assistant that can make administrators
        # is a different product from this one.
        raise PermissionError(f"{role!r} cannot be granted through the assistant.")

    target = _user_by_email(params["email"])
    if target is None:
        raise ValueError(f"No account for {params['email']!r}.")

    if str(target.get("id")) == str(user.get("id")):
        # An admin can still do this in the UI. Refusing here costs them nothing and
        # closes the path injected content aims at first.
        raise PermissionError("You cannot change your own role through the assistant.")

    granted = set(ROLE_PERMISSIONS.get(role, ()))
    held = set(user.get("permissions") or permissions_for(user.get("role")))
    beyond = sorted(granted - held)
    if beyond:
        raise PermissionError(
            f"You do not hold {', '.join(beyond)}, so you cannot grant them.")

    return {"user": await update_user(str(target["id"]), {"role": role}, admin=user)}
```

`_user_by_email` is a thin reader over the users table. `dependents_grant_role` computes `ROLE_PERMISSIONS[new] - ROLE_PERMISSIONS[current]` and adds one item per permission gained, with the person's current role named; wrap the lookup in `try/except` and `.skipped(...)`.

Add `users` to `_MODULES` and register its `DEPENDENTS` entry.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_grant_role.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/users.py backend/app/chat/analysis/__init__.py backend/tests/test_chat_grant_role.py
git commit -m "feat(assistant): grant a role, within three limits

No grant beyond what the caller holds; admin is never grantable, because an
assistant that can make administrators is a different product; and nobody
changes their own role through the assistant, which costs an admin nothing and
closes the path injected content aims at first.

The card names the permissions gained, not the role — 'admin' is not something
an approver can weigh."
```

---

## Task 11: Say what it can change now

**Files:**
- Modify: `backend/app/api/chat_routes.py` (`_system_prompt`)
- Modify: `frontend/components/chat/assistant-panel.tsx` (greeting)
- Modify: `backend/tests/test_chat_prompt_copy.py`

The existing test pairs the claim with the registry: the assistant says it cannot change settings, and the test asserts no action holds `settings:write` or `user:manage`. Both halves are now false. Invert the pairing rather than deleting it — the mechanism is what stops the copy and the registry drifting apart, and it is worth more now that the registry can change things.

- [ ] **Step 1: Rewrite the test**

```python
# backend/tests/test_chat_prompt_copy.py
"""What the assistant says it can do has to match what the registry lets it do.

This file used to assert the opposite. It said the assistant cannot change settings
and checked that no action held settings:write — a pairing that made the claim
falsifiable. Now that the claim has changed, the pairing has to change with it, or
it stops being a check and becomes a comment.
"""
from app.api.chat_routes import _system_prompt
from app.chat.actions import REGISTRY, ActionKind


def test_the_prompt_names_what_it_can_now_change():
    prompt = _system_prompt("/governance", {})
    for word in ("policy", "schedule", "role"):
        assert word in prompt.lower(), f"prompt no longer mentions {word}"


def test_the_prompt_still_refuses_what_the_registry_still_cannot_do():
    prompt = _system_prompt("/governance", {}).lower()
    assert "credential" in prompt or "secret" in prompt or "api key" in prompt
    assert "delete" in prompt and "account" in prompt


def test_no_action_writes_a_credential():
    """The claim above, checked against the code that would have to break it."""
    from app.chat.analysis.settings import ALLOWED_KEYS
    from app.api.system_settings import SENSITIVE_KEYS
    assert not (ALLOWED_KEYS & set(SENSITIVE_KEYS))


def test_no_action_deletes_an_account_or_runs_a_sync():
    for action in REGISTRY.values():
        assert action.id != "users.delete_user", action.id
        assert action.id != "connectors.sync", action.id


def test_every_action_that_changes_who_can_do_what_is_destructive():
    """The grading rule, as a test. An action on user:manage that is not destructive
    would skip the typed target and the named-target check."""
    for action in REGISTRY.values():
        if action.permission == "user:manage":
            assert action.kind is ActionKind.DESTRUCTIVE, action.id
            assert action.target_field, action.id


def test_every_destructive_action_declares_a_target_field():
    """Without one the gate cannot derive a target, and a destructive action with no
    target is one the approval check cannot protect."""
    missing = [a.id for a in REGISTRY.values()
               if a.kind is ActionKind.DESTRUCTIVE and not a.target_field]
    assert not missing, missing
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_prompt_copy.py -q`
Expected: FAIL on the first two — the prompt still says it cannot change settings.

- [ ] **Step 3: Update the prompt**

Replace the closing sentences of `_system_prompt` with what is now true: it can change refresh schedules and collection membership, connector schedules and sync modes, row-filter and masking policies, model configuration, and roles — each with your approval, and the last four asking you to type the name. It cannot write a credential of any kind, delete an account, run a sync, or delete a collection or dashboard.

- [ ] **Step 4: Update the greeting**

Same content, shorter, in `frontend/components/chat/assistant-panel.tsx`. Replace only the greeting string.

- [ ] **Step 5: Verify both halves**

Run: `cd backend && python3.12 -m pytest tests/test_chat_prompt_copy.py tests/ -q -k "chat or capabilit"`
Run: `cd frontend && npm test && npx tsc --noEmit -p tsconfig.json && npm run build`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/chat_routes.py frontend/components/chat/assistant-panel.tsx backend/tests/test_chat_prompt_copy.py
git commit -m "feat(assistant): say what it can change, and what it still cannot

The pairing test is inverted rather than deleted: it now checks that the copy
names what the registry can do, and that the things the copy still refuses —
credentials, account deletion, sync — are things no action can reach."
```

---

## Done

Eleven actions — seven reversible, four behind a gate that asks for the target twice:
once in the user's own words before a card is rendered, and once typed into the card. Nothing
here writes a credential, deletes an account, or runs a sync — spec §13 says so, and
Task 11's tests fail if that stops being true.
