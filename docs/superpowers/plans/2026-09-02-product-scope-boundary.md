# Product scope boundary — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> or `superpowers:executing-plans` to implement this task-by-task. Steps use `- [ ]`.

**Goal:** the console says which of its surfaces this release supports, and a fresh
install renders only the Portable Core — without deleting anything from a deployment
that is already running an add-on.

**Spec:** `docs/superpowers/specs/2026-09-02-product-scope-boundary-design.md`. Read it
first; it carries the measurement the plan argues from and the reasoning behind the
three-state values convention.

**Architecture:** no new subsystem. Two support tiers, *derived* from artifacts the repo
already maintains (`SUPPORT.md`'s add-on list, and the deploy refusal in
`dag_generator.refuse_placeholder_deploy`), carried in the capability payload the console
already fetches. The Helm defaults become three-state — explicit / running / off — using
the `lookup` preserve pattern `templates/secrets.yaml` established.

**Tech stack:** FastAPI + `app/capabilities.py` (pure), Helm templates and `_*.tpl`
helpers, Next.js with `lib/capabilities.tsx`, pytest, `node --test`, and the existing
kind-based CI job.

## Global constraints

- `app/capabilities.py` stays pure and dependency-free: constants and arithmetic, no I/O,
  no imports beyond `typing`. The tests read `SUPPORT.md`; the module never does.
- A tier is derived, never asserted. If a task finds itself writing a capability's tier
  by hand outside `PREVIEW_CAPABILITIES`, the derivation is wrong — fix the derivation.
- No task changes a permission, a gate, or who may reach any route.
- No feature, route or page is removed. `values-onprem.yaml` users keep everything.
- Backend tests run with `python3.12` (`python3` is 3.9 here and cannot parse modern
  syntax). Four `tests/test_webauthn.py` failures are environmental — the `webauthn`
  package is not installed — and are the only failures any task may leave.
- Frontend: `npm test`, `npx tsc --noEmit`, `npm run lint`, and `npm run build` before a
  commit that touches a page. One pre-existing lint warning in `app/query/page.tsx` is
  not yours. Leave `frontend/app/globals.css` alone.
- Each task is one TDD cycle: a failing test that names the defect, the smallest change
  that passes it, the full suites, then the commit message given.

## File structure

| File | Responsibility |
|---|---|
| `SUPPORT.md` | The one place naming which add-ons this release does not support, with an anchored list a test can read. |
| `backend/app/capabilities.py` | `UNSUPPORTED_BACKENDS`, `CAPABILITY_BACKENDS`, `PREVIEW_CAPABILITIES`, the derivation, and the boolean map that now reads the same table. |
| `backend/tests/test_capability_support_tiers.py` | Ties the constants to `SUPPORT.md` and to the deploy refusal. |
| `helm/datapond/templates/_addons.tpl` | `datapond.addonEnabledOrPreserved` — explicit / running / off. |
| `helm/datapond/templates/NOTES.txt` | What this install resolved to, and how to turn each add-on off. |
| `backend/tests/test_helm_addon_defaults.py` | The three-way table offline, the eight templates routing through the helper, and which add-ons each profile renders. |
| `frontend/lib/capability-support.ts` (+ `.test.ts`) | Tier lookup and the two sentences of UI copy. |

---

## A. The tiers, derived

### [ ] A1 — `SUPPORT.md` gets a list a test can hold onto

The support tier for four capabilities is "the add-on behind it is unsupported", and
`SUPPORT.md` is where that is stated — in a sentence. Parsing a sentence makes every
future edit to that paragraph a possible test failure for reasons unrelated to what it
says, so the list gets an anchor and the prose stays prose.

**Files**
- Modify: `SUPPORT.md`
- Modify: `backend/app/capabilities.py`
- Test: `backend/tests/test_capability_support_tiers.py` (create)

Steps:

- [ ] Write the failing test:

```python
"""The add-ons this release does not support, named once."""
import re
from pathlib import Path

from app.capabilities import UNSUPPORTED_BACKENDS

SUPPORT_MD = Path(__file__).resolve().parents[2] / "SUPPORT.md"


def _anchored_addons() -> set:
    """The names between SUPPORT.md's markers, upper-cased to match FEATURE_* flags."""
    body = SUPPORT_MD.read_text()
    block = re.search(r"<!-- unsupported-addons -->(.*?)<!-- /unsupported-addons -->",
                      body, re.S)
    assert block, "SUPPORT.md lost its unsupported-addons anchor"
    return {line.strip("- ").strip().upper()
            for line in block.group(1).splitlines() if line.strip().startswith("-")}


def test_the_code_and_the_document_name_the_same_add_ons():
    """One list, two readers. A name added to the document without a tier — or a tier
    for a name the document no longer disclaims — is a product claim drifting from what
    the console shows."""
    assert set(UNSUPPORTED_BACKENDS) == _anchored_addons()
```

- [ ] Run `cd backend && python3.12 -m pytest tests/test_capability_support_tiers.py -q`
      — fails: `SUPPORT.md` has no anchor and `UNSUPPORTED_BACKENDS` does not exist.
- [ ] Add the anchored list to `SUPPORT.md`, directly under the paragraph that already
      names them, keeping that paragraph unchanged:

```markdown
### Add-ons this release does not support

<!-- unsupported-addons -->
- Trino
- Airflow
- Spark
- Polaris
- RisingWave
- OpenMetadata
- Jupyter
- MLflow
<!-- /unsupported-addons -->
```

- [ ] Add to `backend/app/capabilities.py`, above `compute_capabilities`:

```python
# The add-ons SUPPORT.md disclaims, as FEATURE_* names. Tied to that document by
# tests/test_capability_support_tiers.py — the list lives there for people, here for
# the derivation, and neither may drift.
UNSUPPORTED_BACKENDS = (
    "TRINO", "AIRFLOW", "SPARK", "POLARIS", "RISINGWAVE", "OPENMETADATA",
    "JUPYTER", "MLFLOW",
)
```

- [ ] Run the test — passes.
- [ ] Run the full backend suite.

Commit: `docs(support): the unsupported add-ons become a list a test can read`

### [ ] A2 — which flags can turn a capability on becomes data

The derivation needs the capability→backend relation, and today it is expressions inside
`compute_capabilities` (`trino or polaris or glue`, `_feat(env, "AIRFLOW")`). Extracting
it changes no behaviour and is what makes A3 possible.

**Files**
- Modify: `backend/app/capabilities.py`
- Test: `backend/tests/test_capability_support_tiers.py`
- Test: `backend/tests/test_capabilities.py` if it exists — its existing assertions must
  pass unchanged; that is the proof this task changed nothing.

Steps:

- [ ] Write the failing test:

```python
from app.capabilities import CAPABILITY_BACKENDS, compute_capabilities


def test_every_component_gated_capability_declares_its_backends():
    """A capability with no entry can never earn a tier, and would be silently
    supported forever."""
    gated = {"connectors", "catalog", "query", "dashboards", "pipelines",
             "streaming", "experiments", "notebooks", "lineage"}
    assert set(CAPABILITY_BACKENDS) == gated


def test_the_table_answers_the_same_as_the_flags():
    """The extraction is behaviour-preserving: with a backend on, its capability is on;
    with every backend off, it is off."""
    for capability, backends in CAPABILITY_BACKENDS.items():
        for backend in backends:
            assert compute_capabilities({f"FEATURE_{backend}": "true"})[capability] is True
        assert compute_capabilities({})[capability] is False
```

- [ ] Run it — fails: `CAPABILITY_BACKENDS` does not exist.
- [ ] Add the table and read it where the ORs were:

```python
# Which FEATURE_* flags can turn each component-gated capability on. One source for the
# runtime answer and for the support tier a capability carries.
CAPABILITY_BACKENDS = {
    "connectors":  ("TRINO", "POLARIS", "GLUE"),
    "catalog":     ("TRINO", "POLARIS", "GLUE"),
    "query":       ("TRINO", "ATHENA"),
    "dashboards":  ("TRINO", "ATHENA"),
    "pipelines":   ("AIRFLOW",),
    "streaming":   ("RISINGWAVE",),
    "experiments": ("MLFLOW",),
    "notebooks":   ("JUPYTER",),
    "lineage":     ("OPENMETADATA",),
}
```

In `compute_capabilities`, replace each of those nine entries with a lookup over the
table — `any(_feat(env, flag) for flag in CAPABILITY_BACKENDS[name])` — and leave
everything else exactly as it is: the query-engine and catalog-backend strings, the
`rls` and `ontology` defaults, and the always-true core.

- [ ] Run the test and every existing capability test — all pass, unchanged.
- [ ] Run the full backend suite.

Commit: `refactor(capabilities): which flags enable a capability becomes a table`

### [ ] A3 — the support map, derived and pinned in both directions

**Files**
- Modify: `backend/app/capabilities.py`
- Test: `backend/tests/test_capability_support_tiers.py`

Steps:

- [ ] Write the failing tests:

```python
from app.capabilities import (CAPABILITY_BACKENDS, PREVIEW_CAPABILITIES,
                              UNSUPPORTED_BACKENDS, compute_capabilities)


def test_the_support_map_is_the_derivation_not_a_hand_written_list():
    """Computed here independently: a capability is experimental exactly when every
    backend that can enable it is one the product does not support. That is why query
    and catalog are not — Athena and Glue are supported adapters."""
    expected = {}
    for capability, backends in CAPABILITY_BACKENDS.items():
        if all(backend in UNSUPPORTED_BACKENDS for backend in backends):
            expected[capability] = "experimental"
    for capability in PREVIEW_CAPABILITIES:
        expected[capability] = "preview"

    assert compute_capabilities({})["support"] == expected
    assert set(expected) == {"pipelines", "streaming", "experiments", "notebooks",
                             "lineage"}
    assert "query" not in expected and "catalog" not in expected


def test_no_core_capability_can_be_marked():
    core = {name for name, value in compute_capabilities({}).items()
            if value is True}
    assert not (core & set(compute_capabilities({})["support"]))


def test_the_vocabulary_is_two_words():
    assert set(compute_capabilities({})["support"].values()) <= {"experimental", "preview"}


def test_preview_expires_when_pipelines_stop_compiling_to_placeholders(tmp_path):
    """The tie that makes 'preview' a fact rather than an opinion.

    CORRECTED 2026-09-02, after the implementer found the first version inert: this
    test's earlier form built a string containing `PythonOperator(...)` and asserted
    `refuse_placeholder_deploy` refused it. It does not — the refusal reads the
    `DATAPOND_UNIMPLEMENTED_TASKS` marker the generator writes, not the task text. And
    hand-writing that marker would be worse: such a test passes forever, including
    after the runtime lands, which is the one moment it exists to catch.

    So pin the fact that actually changes — the generator stops emitting placeholder
    tasks. Compile a real pipeline (see tests/test_pipeline_quality_checks.py for the
    fixture shape) and read its DAG.
    """
    from app.pipelines.dag_generator import refuse_placeholder_deploy, unimplemented_tasks

    dag = <the DAG artifact of a minimal compiled pipeline>
    placeholders = unimplemented_tasks(dag)
    assert ("pipelines" in PREVIEW_CAPABILITIES) == bool(placeholders), (
        "the generator no longer emits placeholder tasks, so the declarative pipeline "
        "runtime has landed. Remove 'pipelines' from PREVIEW_CAPABILITIES — the console "
        "is still telling people it cannot deploy."
    )
    if placeholders:
        assert refuse_placeholder_deploy(dag, allow=False), (
            "the generator emits placeholders but the deploy no longer refuses them")
```

- [ ] Run them — fail: no `support` key, no `PREVIEW_CAPABILITIES`.
- [ ] Implement:

```python
# A capability whose own headline feature cannot complete in this release. Stronger
# than `experimental`, and tied to the code that makes it true:
# tests/test_capability_support_tiers.py fails when the deploy stops being refused.
PREVIEW_CAPABILITIES = ("pipelines",)


def support_tiers() -> dict:
    """{capability: tier} for everything this release does not fully support.

    Absent means supported, so a capability added later cannot inherit a tier by
    accident. Derived, never hand-written: experimental is "every backend that can
    enable this is one SUPPORT.md disclaims".
    """
    tiers = {
        capability: "experimental"
        for capability, backends in CAPABILITY_BACKENDS.items()
        if all(backend in UNSUPPORTED_BACKENDS for backend in backends)
    }
    tiers.update({capability: "preview" for capability in PREVIEW_CAPABILITIES})
    return tiers
```

and add `"support": support_tiers()` to the dict `compute_capabilities` returns.

- [ ] Run the tests — pass.
- [ ] Run the full backend suite.

Commit: `feat(capabilities): the payload says what this release supports, derived`

---

## B. The console

### [ ] B1 — the tier's presentation logic, and the two sentences

**Files**
- Create: `frontend/lib/capability-support.ts`, `frontend/lib/capability-support.test.ts`
- Modify: `frontend/lib/capabilities.tsx` — carry `support` from the payload it already
  fetches

Steps:

- [ ] Write `frontend/lib/capability-support.test.ts`: `supportTier("streaming", map)`
      returns `"experimental"`; an absent capability returns `null`; a tier the backend
      sends that this build does not know returns `null` rather than rendering an
      unknown word (a newer backend must not put unlabelled text in the UI);
      `supportBadge("preview").label` is `"Preview"` and its title names the refusal;
      `supportBadge("experimental").title` says the wiring is supported and the upstream
      project is not.
- [ ] Run `cd frontend && npm test` — fails, module missing.
- [ ] Write `frontend/lib/capability-support.ts` with `SupportTier`, `supportTier`,
      `supportBadge`, and a module docstring in the house style pointing at
      `SUPPORT.md` and `app/capabilities.py` as where the fact comes from.
- [ ] Add `support: Record<string, string>` to the capability context in
      `frontend/lib/capabilities.tsx`, defaulting to `{}` — a backend that predates A3
      must render as "everything supported", not crash.
- [ ] Run `npm test`, `npx tsc --noEmit`, `npm run lint`.

Commit: `feat(ui): the console can say which surfaces this release supports`

### [ ] B2 — where a person meets the feature

**Files**
- Modify: `frontend/components/app-sidebar.tsx`
- Modify: `frontend/app/{streaming,notebooks,experiments,pipelines}/page.tsx`
- Modify: the Governance → Lineage tab (`frontend/app/governance/page.tsx` or the
  lineage panel it renders — read which before editing)
- Test: `frontend/lib/capability-support.test.ts` extended with a scan asserting each of
  those files imports `supportBadge`, the same shape
  `lib/permission-source.test.ts` uses for its own repo-wide rule

Steps:

- [ ] Write the failing scan test naming the six files.
- [ ] Run `npm test` — fails, listing them.
- [ ] Sidebar: a small tag beside the item title for any nav entry whose capability
      carries a tier, with the badge's title as its `title` attribute.
- [ ] Each page: one line under the title, from `supportBadge`.
- [ ] `/pipelines` additionally states the split once, in its own words: SQL Transforms
      deploy to Airflow and run; declarative pipelines are preview and the deploy is
      refused. This sentence is the reason the capability keeps one tier — do not try to
      express it in the payload.
- [ ] Run `npm test`, `npx tsc --noEmit`, `npm run lint`, `npm run build`.

Commit: `feat(ui): an experimental surface says so where you meet it`

---

## C. Defaults that narrow without deleting

### [ ] C1 — explicit, else running, else off

**Files**
- Create: `helm/datapond/templates/_addons.tpl`
- Modify: `helm/datapond/values.yaml` (the eight add-on `enabled` keys)
- Modify: the eight add-on templates' guard lines
- Test: `backend/tests/test_helm_addon_defaults.py` (create)

Steps:

- [ ] Write the failing test: rendering with `--set airflow.enabled=true` includes the
      Airflow Deployment; with `--set airflow.enabled=false` it does not; with neither
      (and no cluster, which is what `helm template` is) it does not; and every one of
      the eight add-on templates routes through `datapond.addonEnabledOrPreserved`
      rather than reading `.enabled` directly. Use `helm template` through
      `subprocess`, the way the other `test_helm_*.py` files shell out.
- [ ] Run it — fails, the helper does not exist.
- [ ] Write `helm/datapond/templates/_addons.tpl`:

```
{{/*
Whether an optional add-on renders: explicit → already running → off.

Helm cannot tell an explicit `false` from a defaulted one, so `enabled` is three-state
here. `true` runs it, `false` removes it, and *unset* means "keep it if this namespace
is already running it, otherwise off" — which is what stops an upgrade from deleting
workloads out of a deployment that never chose. Same shape as the explicit → existing →
generated rule templates/secrets.yaml uses for passwords.

Args: dict "root" $ "component" "<values key>" "name" "<Deployment metadata.name>"
*/}}
{{- define "datapond.addonEnabledOrPreserved" -}}
{{- $values := (index .root.Values .component) | default dict -}}
{{- $explicit := index $values "enabled" -}}
{{- if kindIs "bool" $explicit -}}
{{- $explicit -}}
{{- else -}}
{{- if lookup "apps/v1" "Deployment" (.root.Values.namespace | default "datapond") .name -}}true{{- else -}}false{{- end -}}
{{- end -}}
{{- end -}}
```

- [ ] Change each add-on template's guard, passing **the `metadata.name` that template
      actually creates** — read it from the template, do not assume it equals the
      component key:

```
{{- if eq "true" (include "datapond.addonEnabledOrPreserved" (dict "root" $ "component" "airflow" "name" "airflow")) }}
```

- [ ] Add to the test: for each of the eight, the name passed to the helper equals a
      `metadata.name` that template renders. A preserve rule that looks for the wrong
      object silently never preserves.
- [ ] Set the eight `enabled` keys in `values.yaml` to `null`, with the three states
      written out where a reader meets them:

```yaml
# Optional OSS add-ons. Three states, deliberately: `true` runs it, `false` removes it,
# and *unset* (null) means "keep it if this namespace is already running it, otherwise
# off". Unset is what makes a fresh install lean without deleting add-ons from an
# existing deployment on upgrade — see templates/_addons.tpl.
airflow:
  enabled: null
```

- [ ] Run the test, `helm lint` on all six profiles, and the full backend suite.

Commit: `fix(helm): a lean default that does not delete what is already running`

### [ ] C2 — the install says what it resolved to

**Files**
- Create: `helm/datapond/templates/NOTES.txt`
- Test: `backend/tests/test_helm_addon_defaults.py`

Steps:

- [ ] Write the failing test: `helm template` output contains no NOTES (they are not
      rendered by `template`), so assert instead on the file's content — every one of
      the eight components appears, the string `--set <component>.enabled=false` appears
      for turning one off, and the word "preserved" appears. A NOTES.txt that lists only
      some add-ons is worse than none: the operator concludes the rest are off.
- [ ] Run it — fails, the file does not exist.
- [ ] Write `NOTES.txt`: which add-ons this release resolved to on, which were preserved
      because they were already running, and the one-line `--set` that turns each off.
- [ ] Run the test and `helm lint`.

Commit: `feat(helm): the install reports which add-ons it kept, and how to stop`

### [ ] C3 — which add-ons a profile renders becomes an assertion

No test asserts this today, which is why flipping the defaults has nothing to update and
nothing to catch it. Checked before writing this plan: the `helm-lint` CI job renders
seven profiles and asserts only that they render, and the `test_helm_*.py` files pin
security contexts, storage classes, duplicate keys and ordering.

**Files**
- Test: `backend/tests/test_helm_addon_defaults.py`

Steps:

- [ ] Write the failing test: render each of `values.yaml` (base), `values-foundation`,
      `values-prod-single`, `values-aws`, `values-dev`, `values-onprem`,
      `values-quicktest` and assert the exact set of add-on Deployments each contains —
      base and the two AWS profiles and the hybrid overlay lean; on-prem full; quicktest
      seven of eight with spark absent; dev as its file states.
- [ ] Run it — it should pass immediately if C1 is right, and fail loudly if C1 changed a
      profile that states its own values. Either outcome is information: this is the
      measurement of what C1 did, and the plan expects the base and `values-aws` rows to
      differ from what the same test would have asserted before C1.
- [ ] If a profile moved that states its own values, that is a defect in C1 — fix C1, not
      the expectation.

Commit: `test(helm): which add-ons each profile renders, as an assertion`

### [ ] C4 — the preserve branch, on a real cluster

`helm template` never executes `lookup`, so the branch that reads the cluster is
unexercised offline. CI already has a cluster: the job *Fresh install, upgrade and
rollback (ephemeral cluster)* runs `helm install` then `helm upgrade` on kind.

**Files**
- Modify: `.github/workflows/ci.yml` (that job only)

Steps:

- [ ] Add a step after the install and before the existing upgrade: install with one
      add-on explicitly on and `replicas: 0` — the rule looks for the Deployment object,
      not a running pod, and this runner's capacity is already tight (two earlier CI
      fixes were about pod counts). If that template hard-codes its replica count, scale
      the Deployment to zero with `kubectl` after install instead.
- [ ] Add the assertion after the upgrade that omits the flag: the Deployment is still
      there.
- [ ] Add the other direction, which matters more: upgrade again with
      `--set <component>.enabled=false` and assert the Deployment is gone. Preservation
      that cannot be switched off is a leak, not a courtesy.
- [ ] Push the branch and confirm the job passes in CI before the task is complete —
      this is the one task whose verification cannot be local.

Commit: `test(ci): preserving a running add-on across an upgrade, and stopping it`

---

## D. The documents that stop being true

### [ ] D1 — three statements about profiles

**Files**
- Modify: `CLAUDE.md` (the `values-aws.yaml` line)
- Modify: `docs/DEPLOYMENT_PROFILES.md` (the AWS Hybrid Extended row)
- Modify: `README.md` (lines 137-139, which list the four surfaces among what the product
  does — they gain the tier they now carry in the API)

Steps:

- [ ] `CLAUDE.md`: "values-aws.yaml is a compatibility overlay for an existing cluster
      and inherits heavy OSS defaults" is false after C1. Replace with what it now does:
      states none of the add-on flags, so it renders the Portable Core on a fresh install
      and preserves whatever an existing cluster is already running.
- [ ] `docs/DEPLOYMENT_PROFILES.md`: the same correction in its own words, in the row and
      any surrounding prose that repeats it.
- [ ] `README.md`: the streaming/transforms/notebooks/experiments lines say which of them
      are experimental, using the same two words the console uses.
- [ ] Re-read `docs/PRODUCT_CONCEPT.md` for the same claim; correct it if present, leave
      it alone if not — do not rewrite positioning.

Commit: `docs: the profile that inherited heavy defaults no longer does`

---

## Follow-ups filed by this run

### [x] F1 — the `lineage` capability gates nothing a person can see

Found while implementing B2, which had been told to label "the Governance → Lineage
tab". There is no such tab. `frontend/app/governance/page.tsx` has audit, activity,
ai-safety, data-protection, access-control, cost and reports; the only "Lineage" UI in
the console is an ungated card on the Knowledge page, backed by `/api/ai/lineage` —
connector→table→collection lineage, unrelated to OpenMetadata and unrelated to this
capability.

So `FEATURE_OPENMETADATA` turns on a capability that no frontend code consumes: no
`useCapability("lineage")`, no `CapabilityGate`, nothing but a mention in
`lib/product-profile.ts`'s add-on list. After A3 it also carries a support tier that
nothing renders.

This is the shape of `app/permissions.py`'s own rule — "a permission nothing enforces is
a lie" — one level up, and it stayed invisible until someone went looking for the
surface. Two honest resolutions, and the choice is a product decision rather than an
engineering one: give OpenMetadata lineage a surface and gate it on the capability, or
retire the capability and stop implying the deployment has something it does not. What
must not happen is the third option B2 was offered and refused: badging the Knowledge
card, which works regardless, as experimental.

**Resolved 2026-09-03 — retired.** Building the surface would have meant new console UI
for an add-on `SUPPORT.md` disclaims, days after this plan narrowed the product to the
Portable Core; and OpenMetadata already has the honest place to show lineage — its own
UI, which is where connector sync writes the edges. So `lineage` is gone from
`CAPABILITY_BACKENDS` and from `/api/capabilities`, with `test_openmetadata_is_a_service
_not_a_capability` holding the line: the key comes back only together with a screen.
Whether OpenMetadata runs stays visible through Services, which reads
`FEATURE_OPENMETADATA` directly. The Knowledge card was left exactly as it was — ungated
and unbadged — because it needs no add-on to work.

Two consequences worth naming. `product-profile.ts` no longer counts OpenMetadata when
it picks a fallback label, so a deployment running it and nothing else now reads as
Portable Core rather than OSS Extended — which is what the console actually shows, since
that deployment gets no extra page. And `/api/pipelines/{name}/lineage` remains, an
OpenMetadata-backed endpoint no frontend calls; it belongs to Transforms, which this
release already refuses to deploy, so it was left for whoever settles that feature.

### [x] F2 — the scan knew two spellings, and NOTES.txt used a third

Parked at the end of the C-task fix wave, as two findings that were not live defects:
the scan's patterns were narrower than the shapes that occur, and `NOTES.txt:21` held a
second copy of the explicit-vs-preserved rule. They are one problem. The scan matched
the literal `dig "enabled" true .Values.trino`, so `dig "enabled" true (.Values.trino |
default dict)` — the same defaulting read with parentheses, and the exact form
`backend-deployment.yaml` uses six times for other components — was invisible to it. And
NOTES.txt re-derived explicitness with `index ((index $.Values $component) | default
dict) "enabled"`, which names no component at all and so could never be caught by a scan
built from component names.

**Resolved 2026-09-03.** The scan now asks structurally rather than by spelling: inside
one template action, does this template read an `enabled` key that belongs to one of the
eight? Shape — attribute, dig, index, pluck, get, dict literal — no longer matters. A
second rule covers the nameless case: a read of `"enabled"` out of a Values subtree
chosen by a variable. What the detector actually catches is now itself a test, a corpus
of eleven shapes that must be caught and ten reads in the chart today that must stay
legal — including `.Values.trino.rls.enabled` and `.Values.airflow.persistence.enabled`,
two-state sub-options of an add-on that the first, too-broad widening wrongly flagged.

The duplicate copy went by giving `_addons.tpl` the question NOTES.txt was answering
alone: `datapond.addonState` returns *why* — `explicit-on`, `explicit-off`, `preserved`,
`off` — and `addonEnabledOrPreserved` is now a wrapper over it. One `index ... "enabled"`
and one `lookup` remain in the chart. NOTES.txt switches on the string.

Order matters here: the widened scan was written first and failed on NOTES.txt, so the
duplicate was removed under a test that now keeps it gone rather than by inspection.
Verified render-preserving on all nine profiles — object counts equal, and the only
differing lines are the secrets Helm regenerates every render, which a control render of
the same tree twice reproduces exactly. `helm lint` clean on nine profiles; the three
reachable NOTES branches were rendered and read. `preserved` still needs a cluster,
which is CI's ephemeral-cluster job.

## Finish

`/code-review high` over the branch, then a fix pass. Then update
`docs/UTILIZATION_PERSONA_ASSESSMENT.md` §6-2 with what closed and what did not: the
console labels and the lean default are this plan; narrowing the *message* — the README
pitch, the product concept — was named out of scope in the spec and stays open.
