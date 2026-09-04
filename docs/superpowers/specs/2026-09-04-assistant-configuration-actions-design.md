# Assistant configuration actions — design

**Status:** approved in conversation 2026-09-04, not yet implemented.
**Extends:** `2026-08-25-conversational-actions-design.md` (§5.3, the destructive gate it
specified and did not build) and `2026-09-03-assistant-analysis-actions-design.md` (§11,
which deferred this half until the analysis actions existed to produce evidence).

## 1. What this is

The assistant can read the product and diagnose it. It cannot change anything: the
registry holds twenty-nine actions and not one of them writes configuration, because the
2026-08-25 spec grouped every such write behind a gate it declined to build in v1 —
"shipping the actions against the weaker gate is the pairing to avoid."

This document builds that gate and puts four families of configuration behind it.

## 2. Scope

**In.** Reversible operational settings; governance policy writes; system settings
excluding every credential; role assignment.

**Out, and deliberately.**

- **Credentials of any kind.** No action may write an API key, a password, or a
  connection secret, and no action may read one back into a card. §7.
- **Account deletion.** Removing a person is done in the UI, deliberately, by someone who
  went there to do it. The assistant adds nothing to that but a way to do it by accident.
- **Anything the analysis branch already refuses:** running a sync, deleting a collection,
  deleting a dashboard.

## 3. What makes an action destructive

`ActionKind.DESTRUCTIVE` has existed in the enum since v1 without a single member. It
gets members here, graded per action and declared rather than inferred — and the rule for
grading is written down, because the next person adding an action needs to reach the same
answer without asking:

> **An action is destructive when undoing it needs information the product no longer
> holds, or when it changes who can do what. Everything else is a mutate.**

Applied:

| Action | Grade | Why |
|---|---|---|
| Budget alert threshold | mutate | The old number is on screen; set it back |
| Refresh schedule on/off and interval | mutate | Same |
| Connector schedule, sync mode | mutate | Same |
| Collection member add / remove | mutate | Re-add restores it exactly |
| RLS or masking policy **create** | mutate | Delete it |
| RLS or masking policy **delete** | **destructive** | The policy body is gone |
| Model provider or embedding model swap | **destructive** | The previous value is a secret we will not show, and every later call changes cost and destination |
| Role grant | **destructive** | Changes who can do what |

A mutate uses the preview → approve card that already exists and works. A destructive
adds the three things §4 describes.

## 4. The destructive contract

Three fields, all computed server-side, on top of today's preview:

- `target` — the canonical name the user must type. Derived from the validated params,
  never from the model's prose.
- `dependents` — what breaks or changes. §6.
- `named_by_user` — whether the user named this target themselves. §5.

**At propose time,** a destructive action whose `named_by_user` is false is refused. No
card is rendered. The model cannot get a confirmation dialog in front of someone for a
target that person never mentioned.

**At approve time,** the request carries `typed_target` in addition to the invocation id.
The server compares it to the stored canonical `target`; a mismatch refuses without
executing. Approval still posts the id and never the parameters — the approved artifact
and the executed artifact remain the same server-side record, which is the property v1
called out as worth stating twice.

## 5. "Named by the user"

The corpus is **the user-role turns in the request's history, plus the current message.**
Assistant turns are excluded, and that exclusion is the whole mechanism: it is what stops
a table comment, a column name or a document chunk from being laundered into "the user
asked for this" by appearing in something the model said.

Matching normalises both sides — casefold, strip quotes and backticks, treat `.`, `/` and
`:` as separators, and compare the trailing segment as well, so a policy on
`crm.customers` counts as named when the person wrote "the customers policy".

The outcome is recorded on the invocation: which turn matched, and on what. "Why was this
allowed?" is a question that gets asked later, and the answer should not require
reconstructing a conversation nobody kept.

A user's own history is client-supplied, so in principle it could be forged — but forging
your own history to approve your own action buys nothing, because typing the target name
was always available. The check defends against content the model read, not against the
person at the keyboard.

## 6. Dependents

"Are you sure?" is not a confirmation. Each destructive action computes what actually
changes:

- **RLS policy delete** — whether the table keeps any filtering at all once this policy is
  gone, and which roles can see rows afterwards that they cannot see now.
- **Masking policy delete** — the columns that stop being masked, and whether PII was
  detected in them.
- **Role grant** — the permission difference, named. Not "admin", but the specific things
  this person will be able to do that they cannot do today.
- **Model provider or embedding model swap** — the logical models that re-point, and **the
  existing collections whose `embed_model` will no longer match the configured one.**
  That mismatch degrades retrieval with nothing logged anywhere;
  `knowledge.diagnose_collection` was built to find it after the fact, and this shows it
  before.

**A dependents list that could not be computed is never rendered as empty.** If the PII
scan cannot run, or the catalog is unavailable, the card says so in the same language the
analysis actions use. An empty list reads as "nothing depends on this", and that is the
confident wrong answer this product keeps having to remove.

## 7. Credentials

The system-settings action does not take a free-form patch. It takes a **field
allowlist**, and a key outside that list is refused **at execution as well as in the
schema** — the settings body is a dictionary by nature, so `extra="forbid"` on a params
model does not reach it.

No credential field is on the allowlist. The executor neither writes a secret nor reads
an existing one back into a card, so no secret has a path into a model prompt at any
point in the flow.

## 8. Role assignment

Three constraints, all enforced at execution:

1. **No grant may exceed the caller's own permissions.** Computed as a set comparison
   against the caller's effective set, so a scoped service key is bounded by its scopes
   here exactly as it is everywhere else.
2. **`user:manage` is never grantable through the assistant.** It can make more
   administrators, and an assistant that can make administrators is a different product.
3. **Nobody may change their own role through the assistant.** A holder of `user:manage`
   can already do this in the UI, so the constraint costs them nothing — and it closes the
   path that injected content would aim at first.

## 9. The catalogue

| Action | Permission | Grade |
|---|---|---|
| `spend.set_budget_alert` | `settings:write` | mutate |
| `knowledge.set_refresh_schedule` | `knowledge:write` | mutate |
| `knowledge.add_member` / `knowledge.remove_member` | `knowledge:write` | mutate |
| `connectors.set_schedule` | `connector:write` | mutate |
| `connectors.set_sync_mode` | `connector:write` | mutate |
| `governance.create_rls_policy` | `governance:write` | mutate |
| `governance.create_masking_policy` | `governance:write` | mutate |
| `governance.delete_rls_policy` | `governance:write` | destructive |
| `governance.delete_masking_policy` | `governance:write` | destructive |
| `settings.set_model_config` | `settings:write` | destructive |
| `users.grant_role` | `user:manage` | destructive |

Every one of these is capability-gated the way §3 of the analysis spec requires wherever
its component is optional, and every executor calls the service function directly.

One row carries a known unknown. `/settings/ai/budget-alerts` exists as a **GET**; where
the threshold is *written* was not established during design — most likely through
`/settings/system`, which is why the action is listed under `settings:write`. The plan
resolves this by reading the code, and if no writable path exists, `spend.set_budget_alert`
is dropped rather than invented.

**The implementation plan must read each handler's real signature and return shape before
writing the executor.** The analysis branch shipped one crash and one silently disabled
feature from assuming payload shapes, and both were caught only in review; the mocks
encoded the same assumption, so the tests passed for the wrong reason.

## 10. Audit

Every destructive invocation records the action, the target, the dependents that were
shown, the evidence for `named_by_user`, the typed-target comparison, and the outcome —
through the same `record_audit` path the gate already uses.

## 11. Testing

The gate is tested with no model in the loop:

1. A destructive action whose target appears in no user turn is refused at propose.
2. A target that appears only in an **assistant** turn is refused — the laundering case.
3. An approve carrying a mismatched `typed_target` does not execute.
4. A settings key outside the allowlist is refused at execution even when the schema let
   it through.
5. A role grant exceeding the caller's permissions is refused; so is granting
   `user:manage`; so is changing one's own role.
6. Dependents that cannot be computed render as "not checked", never as an empty list.
7. Normalisation: `crm.customers` counts as named when the user wrote "customers", and
   does not count when the user wrote a different table in the same namespace.

## 12. Phases

1. The destructive contract — grade, `target`, `typed_target`, `named_by_user`, refusal
   paths — with no destructive action registered. The gate is the part that must be right
   and it is testable alone.
2. The five reversible mutates. They need no new gate and can ship behind the existing
   card.
3. Dependents, per destructive action.
4. The four destructive actions.
5. The copy, and the pairing test inverted: the assistant now says what it *can* change,
   and the test fails if the registry and the sentence disagree.

## 13. What comes after

Nothing in this design lets the assistant delete an account, write a credential, or run a
sync. Those stay UI-only, and the next person to propose moving one should have to argue
against §2 rather than discover the boundary by reading code.
