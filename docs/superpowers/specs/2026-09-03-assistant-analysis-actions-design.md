# Assistant analysis actions — design

**Status:** approved in conversation 2026-09-03, not yet implemented.
**Extends:** `2026-08-25-conversational-actions-design.md`, whose §13 phase 4 is
"review before extending — whether destructive actions are worth building at all is a
decision to make against observed use, not now." This document is the first half of
that review, and it answers only the analysis half.

## 1. What this is

The assistant can already act. `backend/app/chat/` holds a registry of twelve actions,
a double permission gate, a preview → approve → execute flow, an invocation store and
audit events. The model never composes a request: it picks an `id` from the registry
and supplies parameters validated against that action's pydantic model, so a catalog
column named `-- ignore prior instructions` is an identifier, not an instruction.

What it cannot do is see most of the product. Of the twelve actions, seven are catalog
and query, three are knowledge, one is governance and one is spend. Sources, service
health, storage, system events, quality checks, pipeline runs and the audit log have no
assistant surface at all, so the questions people actually ask on those screens — *why
did last night's sync fail, is this collection still worth querying, why did spend go
up* — cannot be answered without leaving the panel.

This design adds that reach. It adds no ability to change anything.

## 2. Scope

**In.** Read and analysis actions across the Portable Core and the add-ons a deployment
has actually enabled; a small number of composite diagnostics; a third gate so that an
action for a disabled component is never offered.

**Out, and deliberately.** Every write the earlier spec excluded stays excluded:
deletes, `connectors.sync` execution, `settings.*`, `user.*`, and every governance
write. Those still need the destructive gate of that spec's §5.3, which still does not
exist. Shipping strong actions against a weak gate is the pairing to avoid, and it is
the pairing this design continues to avoid.

The order is deliberate rather than timid. The earlier spec asked for the extension
decision to be made "against observed use"; there is no observed use of configuration
actions because there are none. Widening reads first produces the invocation records
that make the configuration decision evidential instead of speculative.

## 3. The capability gate

`Action` gains one field:

```python
capability: Optional[str] = None   # a key of compute_capabilities(), or None for core
```

It is enforced exactly the way `permission` is — twice, for two different reasons.

**At proposal time,** `actions_for(permissions, page, capabilities)` takes a third
filter. An action whose capability is not exactly `True` is not in the list handed to
the model, so the model cannot propose it and cannot explain what the deployment is
missing.

**At execution time,** `gate._authorize` checks again against the server's own
computation. The map that arrives from a client is never the one that decides; the first
gate is UX, the second is the control.

It must not compute that answer itself. `main.py` already defines `require_capability`,
a dependency that gates the catalog, query and connectors routers on
`compute_capabilities(os.environ)`, and a second implementation beside it would be a
second answer to the same question — the failure this session's other work kept finding.
So `require_capability` moves out of `main.py` into `component_guard.py`, beside
`require_component`, and both the routers and the action gate call it. Nothing about its
behaviour changes; it stops living in the file that assembles the app, where nothing
else can import it.

**Fail-closed, twice over.** A capability whose value is anything but `True` — `False`,
absent, a string — drops the action. A caller that supplies no map at all loses every
capability-bound action rather than gaining them.

This closes a gap that predates the feature. `actions_for` filters by permission and
page only, so on a deployment with Trino and Athena off — the Portable Core default —
`catalog.describe_table` is still offered to the model, proposed, and then fails at the
route. The existing seven get their capabilities as part of this work:

| Action | capability |
|---|---|
| `catalog.describe_table`, `catalog.find_tables`, `catalog.explain_relationships` | `catalog` |
| `query.generate_sql`, `query.explain_plan`, `query.run` | `query` |
| `dashboard.save` | `dashboards` |
| knowledge, governance and spend actions | none — Portable Core |

A capability name that does not exist fails closed, which means a typo silently hides an
action forever rather than raising. §9 pins that with a test rather than a convention.

## 4. The analysis catalogue

All `READ`: nothing changes, so no approval card. All `("*",)`: the panel is on every
page, and "why did the sync fail" is not a question about which screen you are looking
at. That is the judgement the existing catalogue already made when `catalog.find_tables`
and the query actions were widened from `/query` to everywhere.

| Action | Action permission | Capability | Reads | Route requires today |
|---|---|---|---|---|
| `connectors.list_sources` | `connector:read` | `connectors` | `/connectors/connections` | `connector:read` |
| `connectors.sync_history` | `connector:read` | `connectors` | `/connectors/{id}/history` | any signed-in user |
| `connectors.quality_checks` | `connector:read` | `connectors` | `/connectors/{id}/quality` | any signed-in user |
| `platform.service_health` | `service:manage` | — | `/services/{s}/health` | any signed-in user |
| `platform.service_metrics` | `service:manage` | — | `/services/{s}/metrics` | any signed-in user |
| `platform.recent_events` | `service:manage` | — | `/system/events` | `service:manage` |
| `storage.overview` | `service:manage` | — | `/storage/overview` | any signed-in user |
| `knowledge.list_collections` | `knowledge:read` | — | `/ai/collections` | `knowledge:read` |
| `knowledge.collection_composition` | `knowledge:read` | — | `/ai/collections/{n}/composition` | `knowledge:read` |
| `governance.policy_coverage` | `governance:read` | — | `/governance/rls/coverage` | `governance:read` |
| `governance.summary_stats` | `governance:read` | — | `/governance/stats` | `governance:read` |
| `pipelines.recent_runs` | `pipeline:write` | `pipelines` | `/pipelines/{n}/runs` | any signed-in user |

Executors call the same service functions the routes call, not the routes over HTTP —
the existing executors already do this, and it keeps one permission check rather than
two disagreeing ones.

### 4.1 Where the action is stricter than the route

The last column is not decoration. Six of these endpoints are reachable by any
signed-in user today: service health and metrics, storage overview, connector history
and quality, and pipeline runs. The actions above are gated harder than that, on the
permission that names the domain.

That is the deliberate direction. The assistant is a wider door than a screen — it
answers from any page, it composes across sources, and its output is narrated rather
than read — so where the two boundaries disagree, the action takes the stricter one. The
cost is an inconsistency worth stating plainly: a `viewer` can open the Storage screen
and read the same numbers the assistant will decline to fetch for them.

The alternative, tightening those six routes to match, is the better fix and is **not**
part of this work. It removes screens from roles that can see them today — Storage and
Services are core navigation for everyone — so it is a product decision with its own
blast radius, not a detail to bundle into an assistant feature. It is filed in §11.

**Among the add-ons, only Transforms.** Streaming, Notebooks and Experiments get
nothing. The operational question people ask about them — is it running — is already
answered by `platform.service_health`, and anything past that means cutting a new
assistant surface into features this release labels preview or experimental. If use
shows otherwise, adding one is a module and a table row.

## 5. Diagnostics

Three composite actions, each answering a question that spans sources. All three return
the same shape:

```python
{
  "subject": str,            # what was examined, echoed back
  "facts": dict,             # measurements, server-side
  "signals": [               # judgements, server-side
    {"severity": "ok" | "warn" | "bad", "statement": str, "evidence": dict},
  ],
  "not_checked": [str],      # what could not be looked at, and why
}
```

Thresholds live in the server, not in the prompt. The model narrates `signals`; it does
not decide what counts as stale or expensive. A threshold in a prompt is a threshold
nobody can test.

`not_checked` is the honesty mechanism and is not optional. A diagnosis that quietly
skips what it could not reach — an add-on that is off, an endpoint the caller lacks
permission for, a history table with no rows yet — reads to the model as a clean bill of
health, and the model will say so. Every executor populates it or returns an empty list
it can defend.

### 5.1 `knowledge.diagnose_collection` — `knowledge:read`

Facts: chunk count, `source_group` count, `last_refreshed_at`, `refresh_enabled` and
interval, member count and owner, the embedding model recorded on the chunks against the
one currently configured.

The last is the reason this action is worth building. A collection embedded with one
model and queried through another degrades retrieval silently: nothing errors, nothing
appears in any log, and the only symptom is worse answers. Nothing in the console
surfaces it today.

Signals: stale against its own schedule; empty or near-empty; embedding-model mismatch;
reachable by nobody but its owner.

### 5.2 `connectors.diagnose_sync` — `connector:read`, capability `connectors`

Facts: last run outcome and error text, duration trend across recent history, quality
findings (row-count drift ±20% warn / ±50% alert, null-rate checks), configured schedule
against actual last run, and the knowledge collections that name this source as a sink.

Signals: last run failed; a missed schedule window; duration trending up; quality check
tripped; a downstream collection that was invalidated but has not re-embedded.

### 5.3 `spend.diagnose_change` — `spend:read`

Facts: two windows compared, broken down by model and by actor, with the movers ranked.

The signal that matters is the one a single-window summary cannot give: whether spend
rose because of **volume** or because of **unit price** — someone switching to a costlier
model moves the total without moving the call count. `spend.summarize` answers "what did
we spend"; this answers "why did it change". Actor attribution stays at exactly the level
`spend.summarize` already returns, so this action widens no privacy boundary.

## 6. Audit and PII — aggregates only

Two actions, and a rule about how they are built.

- **`audit.activity_summary`** — `audit:read`. Event counts by type and outcome over a
  window, the denial trend, the busiest period. It returns no actor identifier, no target
  identifier and no free-text detail.
- **`governance.pii_summary`** — `governance:read`. Total detections, distribution by
  category, per-table counts. It returns no detected value and no sample row.

**Neither may be implemented by calling an existing list endpoint and trimming the
result.** Trimming puts raw records in process memory, and then the boundary is a line of
mapping code that a later change can widen without anyone noticing. Both are dedicated
aggregate queries, so there is no path along which a raw audit record or a detected value
reaches the model. §9 tests the boundary rather than trusting it.

"Who read what" stays a question for the Governance screen, which shows it to the same
people under the same permission, with no model in the middle.

## 7. Module structure

```
backend/app/chat/analysis/
  __init__.py       assembles the domain modules into one tuple
  catalog.py        query.py        dashboards.py     ← the existing twelve, moved
  connectors.py     platform.py     knowledge.py
  governance.py     spend.py        pipelines.py      ← new
```

Each module exports `ACTIONS: tuple[Action, ...]` and defines its executors beside the
declarations. `actions.py` keeps the vocabulary — the `Action` type, `resolve`,
`validate_params`, `actions_for`, `tool_definitions` — and assembles the registry.

The existing twelve move as part of this work. `actions.py` already says registration of
what an action does "lives with the action's own module" while `executors.py` holds all
of them in one 318-line file; adding ten more without fixing that leaves two conventions
in one registry, which is the shape that keeps producing second copies. The move is
mechanical — the file is already sectioned by domain comment.

## 8. Copy that must change

`_system_prompt` in `chat_routes.py` and the panel's greeting in `assistant-panel.tsx`
both describe today's narrower reach. Left alone they become false the moment this ships.
Both are updated to describe the wider read surface, and both keep the sentence that
stays true: **it cannot change settings and cannot delete anything.**

## 9. Testing

No model in the loop. The gate is the part that must be right, and it is testable alone.

1. **Capability double-gate.** With a capability false, its actions are absent from
   `tool_definitions`, and a forged `action_id` naming one is refused by `_authorize`.
2. **Fail-closed.** With no capability map, every capability-bound action disappears;
   with a capability present but not exactly `True`, likewise.
3. **Registry integrity.** Every action's `permission` is in `permissions.ALL_PERMISSIONS`
   and every non-null `capability` is a real key of `compute_capabilities({})`. Without
   this, a typo means "always hidden" and no test, log or error ever says so.
4. **Aggregate boundary.** Feed the audit and PII executors a fixture whose records carry
   actor names, target ids and detected values; assert none of those strings appear
   anywhere in the returned structure.
5. **Diagnostics.** With a dependency unavailable, `not_checked` names it; the summary
   does not claim health it did not verify.
6. **Registry-wide invariants.** Every params model forbids extra fields, and every id
   is `domain.verb`. Every action *this design adds* is `READ`; the registry as a whole
   is not, because `query.run`, `dashboard.save` and `knowledge.create_collection`
   already exist as `CREATE`.

## 10. Phases

1. Capability gate on the existing twelve, with tests. Ships alone and fixes a live gap.
2. Module split — the existing twelve move; no behaviour change, proven by the tests
   already covering them.
3. Thin reads (§4), one commit per domain module.
4. Diagnostics (§5).
5. Audit and PII aggregates (§6) plus the copy change (§8).

Phases 1 and 2 are worth landing before the rest whatever happens to it: the first is a
bug fix, the second makes every later phase a small diff.

## 11. What comes after

**The loose routes — decided 2026-09-04: leave them.** `/services/{s}/health`, `/services/{s}/metrics`,
`/storage/overview`, `/connectors/{id}/history` and `/connectors/{id}/quality`, plus
`/pipelines/{n}/runs`, require only a signed-in user, while the permission vocabulary has
names for exactly what they expose. Whether to tighten them is a product decision —
Storage and Services are core navigation, so tightening removes screens from roles that
have them — and it is unrelated to the assistant except that building this made the gap
visible.

The decision is to leave them open and keep the assistant stricter. Storage and Services
are core navigation, so tightening removes screens from `viewer` and `business_analyst`,
and what those endpoints expose is operational state — sync timings, pod health, bucket
sizes — not customer data. The wide door is the one that mattered, and it is already
shut: every action over these endpoints is gated on the permission that names the domain,
so the assistant cannot be used to read around the gap. §4.1 records the asymmetry that
follows, and it stands rather than being temporary.

**The configuration half.** It needs the destructive gate of
§5.3 in the earlier spec — typing the target's name, showing dependent objects, refusing
a target the user never named in their own words — and a decision about which settings
are eligible at all. That decision should be made against the invocation records this
work produces, which is the sequence the earlier spec asked for.
