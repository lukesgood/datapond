# Product scope boundary — design

> Closes §6-2 of `docs/UTILIZATION_PERSONA_ASSESSMENT.md` ("제품 범위를 Portable Core로
> 고정"). Written 2026-09-02, against the code as it stands at `5f4f09c`.

## The problem, measured

The assessment's judgement was that DataPond is *"버려야 할 프로토타입이 아니라 좁혀야 할
제품"* — not a prototype to discard but a product to narrow — and that the largest
business risk is breadth: a UI wide enough to imply support the product does not offer.

Three things are already true and are **not** the problem:

- Capability gating works. `frontend/components/app-sidebar.tsx` hides a nav item whose
  capability is false, and `conditional-layout.tsx` fails a direct route closed.
- The AWS profiles already disable all four surfaces. `values-foundation.yaml` and
  `values-prod-single.yaml` set `airflow`, `risingwave`, `jupyter` and `mlflow` to
  false, so the live deployment has never shown them.
- `SUPPORT.md` already says the honest thing: the OSS add-ons "are configuration around
  upstream projects… we are not in a position to support those projects themselves",
  and declarative pipelines "compile to placeholder tasks and refuse to deploy… They
  are not a supported feature."

What is left is the gap between those three and what a person sees:

1. **The base `values.yaml` enables all eight add-ons.** A deployment that does not pick
   a profile gets the wide platform, and `values-aws.yaml` — which sets none of them —
   inherits exactly that. The product's own documentation calls this out as a defect.
2. **Nothing in the console repeats what SUPPORT.md says.** Turn Airflow on and you get
   a pipeline builder whose Deploy button returns 501 with a written reason, and no
   indication of that until you press it.
3. **Two different promises wear one face.** Streaming, Notebooks, Experiments and SQL
   Transforms *work* when their add-on is on. The declarative pipeline builder cannot
   finish its own workflow. Calling both "optional" flattens a distinction that matters
   to someone deciding whether to build on one.

## What this design does not do

- It does not remove any feature, route or page. `values-onprem.yaml` users run Jupyter,
  MLflow and RisingWave deliberately; taking those away would be a different decision
  with different owners.
- It does not change any permission, gate or authorization path.
- It does not implement the declarative pipeline runtime. That surface stays refused;
  this design makes the refusal visible earlier.
- It does not touch the product's positioning documents beyond making false statements
  true (see §5). Rewriting the pitch is not an engineering task.

## 1. Two tiers, and the words for them

A capability carries at most one support tier. Absent means supported.

| Tier | Capabilities | What it means |
|---|---|---|
| *(none)* | knowledge, ai, governance, storage, services, system, settings, dashboards, connectors, catalog, query | The Portable Core. Supported. |
| `experimental` | streaming, notebooks, experiments, lineage | Works when its add-on is enabled. It is configuration around an upstream project; the wiring is supported, the project is not. |
| `preview` | pipelines | The capability's headline feature — declarative pipelines — compiles to placeholder tasks and refuses to deploy. |

The wording comes from `SUPPORT.md`, which already carries both sentences. This design
does not invent a third description of the same fact; it moves the two that exist to
where someone meets the feature.

**The `pipelines` capability hosts both halves and the design keeps one tier per
capability.** `/pipelines` lists SQL Transforms (which deploy to Airflow and run) beside
saved declarative pipelines (which do not deploy). The finer distinction is stated on
that page, in one sentence, because that is the only place it exists. Encoding it in the
capability contract would put a two-valued fact in a one-valued field for every consumer.

Note the escape hatch that already exists: `PIPELINES_ALLOW_PLACEHOLDER_DEPLOY=true`
makes the deploy proceed. The `preview` tier describes the default; the page's sentence
is about what the API refuses, so an operator who has set that flag is not told a lie —
the refusal simply does not fire.

## 2. Backend contract — the tier is derived, not decided here

A tier written by hand is an opinion with nothing keeping it true. Both tiers in this
design are already provable against artifacts the repository maintains for other
reasons, so the design makes them derivable and the tests do the deriving.

**What `experimental` means, mechanically.** `SUPPORT.md` names the eight OSS add-ons it
does not support: Trino, Airflow, Spark, Polaris, RisingWave, OpenMetadata, Jupyter,
MLflow. A capability is `experimental` exactly when *every* backend that can turn it on
is one of those. That rule gives the right answer without a judgement call:

| Capability | Backends | Experimental? |
|---|---|---|
| pipelines | AIRFLOW | yes — its only backend is unsupported |
| streaming | RISINGWAVE | yes |
| notebooks | JUPYTER | yes |
| experiments | MLFLOW | yes |
| lineage | OPENMETADATA | yes |
| query, dashboards | TRINO **or** ATHENA | no — Athena is a supported AWS adapter |
| catalog, connectors | TRINO, POLARIS **or** GLUE | no — Glue is supported |

For this to be derivable, the capability→backend relation has to exist as data rather
than as expressions inside `compute_capabilities`. So `app/capabilities.py` gains:

```python
# Which FEATURE_* flags can turn each component-gated capability on. The single source
# for both the runtime answer and the support tier a capability carries.
CAPABILITY_BACKENDS = {
    "connectors": ("TRINO", "POLARIS", "GLUE"),
    "catalog":    ("TRINO", "POLARIS", "GLUE"),
    "query":      ("TRINO", "ATHENA"),
    "dashboards": ("TRINO", "ATHENA"),
    "pipelines":  ("AIRFLOW",),
    "streaming":  ("RISINGWAVE",),
    "experiments": ("MLFLOW",),
    "notebooks":  ("JUPYTER",),
    "lineage":    ("OPENMETADATA",),
}
```

`compute_capabilities` reads that table for those nine instead of repeating the OR
expressions inline. Everything else in the function — the query-engine strings, the
`rls` and `ontology` defaults, the always-true core — is untouched.

**What `preview` means, mechanically.** `pipelines` carries the stronger tier because
`app/pipelines/dag_generator.refuse_placeholder_deploy` refuses the deploy when the
generated DAG contains placeholder tasks. That refusal is the fact; the tier is its
label. The tie is asserted in both directions: the tier is `preview` only while the
refusal still fires on a placeholder DAG, and if the refusal ever stops firing the test
demands the tier change with it.

**The runtime shape.** `compute_capabilities(env)` returns its boolean map plus
`"support": {...}` built from `CAPABILITY_BACKENDS`, `UNSUPPORTED_BACKENDS` (the eight
names, kept beside it) and the one `preview` promotion. Still pure, still no I/O — the
derivation is arithmetic over two constants, and it is the *tests* that check those
constants against `SUPPORT.md` and against the refusal code.

Only non-supported capabilities appear in the map; absent means supported.

**Tests** (`backend/tests/test_capability_support_tiers.py`):

- `UNSUPPORTED_BACKENDS` equals the add-on list parsed out of `SUPPORT.md`. Change one
  and the other fails — the same technique `test_role_seed_migration.py` uses to tie
  `ROLE_LABELS` to the seeded prose.
- Every key of `CAPABILITY_BACKENDS` is a real capability, and every component-gated
  capability appears in it — a capability with no backing table entry would silently
  never earn a tier.
- The support map equals the derivation, computed independently in the test from those
  two constants, so a hand-edit to the map alone fails.
- `pipelines` is `preview` **and** `refuse_placeholder_deploy` still refuses a DAG built
  from placeholder tasks; the second assertion is what makes the first expire when the
  runtime lands.
- No capability the module reports as unconditionally `True` carries a tier.
- `compute_capabilities({})` still answers with the support map when every flag is off,
  because the console asks before it knows what is enabled.

## 3. Console

Presentation logic in `frontend/lib/capability-support.ts`, tested with `node --test`:

```ts
export type SupportTier = "experimental" | "preview"
export function supportTier(capability: string, support: Record<string, string>): SupportTier | null
export function supportBadge(tier: SupportTier): { label: string; title: string }
```

`supportBadge` holds the two sentences — the only place UI copy for this lives:

- `experimental` → label "Experimental", title "Configuration around an upstream
  project. The wiring is supported; the project itself is not."
- `preview` → label "Preview", title "Not deployable in this release: pipelines compile
  to placeholder tasks and the deploy is refused."

Rendered in two places:

- **Sidebar** (`components/app-sidebar.tsx`): a small tag beside the item's title,
  from the capability context the sidebar already reads.
- **Page header**: one line under the title on `/streaming`, `/notebooks`,
  `/experiments`, `/pipelines`, and on the Governance → Lineage tab, which is where the
  `lineage` capability surfaces (its nav item is core; only the tab is gated).

`/pipelines` additionally states the split, once, in its own words: SQL Transforms
deploy to Airflow and run; declarative pipelines are preview and the deploy is refused.

The capability payload is already fetched by `frontend/lib/capabilities.tsx`; this adds
`support` to what that context carries. No new request.

## 4. Defaults — lean for a new install, preserved for an existing one

Flipping the base defaults narrows what a fresh install renders. Applied naively it also
deletes running workloads from any deployment that installed without a profile and
without `--set`, on the next upgrade, silently. That is not an acceptable cost and the
chart already has the pattern that avoids it.

`templates/secrets.yaml` resolves a generated password **explicit → existing → new**,
using `lookup` to find what is already in the cluster. The same three-way rule applies
here, one level up:

```
{{- define "datapond.addonEnabled" -}}
  explicit .Values.<component>.enabled (true or false)  → use it
  unset (null)                                          → running in this namespace? keep it : off
{{- end -}}
```

So `helm/datapond/values.yaml` sets the eight add-ons to `enabled: null` — *unset*, which
is a different statement from `false` — and each add-on template asks the helper instead
of reading the value directly. The result:

- **A new install** renders none of the eight: the lookup finds nothing.
- **An existing install** that never chose keeps exactly what it is running, and
  `NOTES.txt` says which components were preserved and the one-line `--set` that turns
  each off. The narrowing reaches it when its operator decides, not when they upgrade.
- **Any profile that states a value** — dev, on-prem, quicktest, foundation,
  prod-single — is unaffected, because explicit wins. Verified: quicktest sets seven of
  eight true and spark false; foundation and prod-single set all eight false.
- **`values-aws.yaml`** states none of them, so a fresh AWS-hybrid install becomes lean
  and an existing one keeps what it has. This is the correction the assessment asked
  for, delivered without taking anything away from a running cluster.

`helm template` has no cluster, so the lookup returns empty and CI renders the lean
shape deterministically. That is the shape the new render test pins.

Checked, rather than assumed: **no test asserts which workloads a profile renders.** The
`helm-lint` CI job (`.github/workflows/ci.yml`) renders seven profiles and asserts only
that each renders without error, and the `backend/tests/test_helm_*.py` files pin
security contexts, storage classes, duplicate keys and ordering — never a workload list.
So this change has no existing expectation to update and nothing that would catch it
going wrong. The plan adds that check: a test that renders each profile and pins which
of the eight add-on Deployments appear, so the base profile's leanness and the on-prem
profile's fullness are both assertions rather than intentions.

## 5. Documents

Only statements that become false, or were already false:

- `CLAUDE.md` — "values-aws.yaml is a compatibility overlay for an existing cluster and
  inherits heavy OSS defaults" stops being true.
- `docs/DEPLOYMENT_PROFILES.md` — the AWS Hybrid Extended row says the same thing.
- `README.md:16` lists the add-ons as "Optional and capability-gated", which stays true,
  and `README.md:137-139` lists streaming/transforms/notebooks/experiments among what
  the product does. Those lines gain the tier they now carry in the API.
- `SUPPORT.md` — unchanged. It is the source this design quotes.

## Testing

| What | Where |
|---|---|
| The support map's keys, vocabulary, and that no core capability carries a tier | `backend/tests/test_capability_support_tiers.py` |
| `supportTier` / `supportBadge` behaviour, including an unknown tier from a newer backend | `frontend/lib/capability-support.test.ts` (`node --test`) |
| The three-way resolution: explicit true, explicit false, and unset-with-no-cluster | `backend/tests/test_helm_addon_defaults.py`, rendering with and without overrides |
| Which add-on Deployments each profile renders | the same file — the check that does not exist today |
| Every add-on template asks the helper rather than reading `.enabled` directly | the same file, a scan over the eight templates |
| Nothing else changed about who may reach these routes | the existing permission and route-inventory suites, unchanged and still green |

## What remains, after both risks were designed out

The two risks this design started with are gone as risks: an existing deployment loses
nothing on upgrade (§4), and neither tier is a standing opinion (§2). What is left is
smaller and stated so it is not discovered later.

- **The preserve branch cannot be tested without a cluster.** `helm template` never
  exercises `lookup`; the tests cover explicit-true, explicit-false and unset-without-a
  -cluster, and assert every add-on template routes through the helper. The branch that
  reads a live cluster is exercised by the ephemeral-install CI job and by the next real
  upgrade, and it fails safe: a lookup that returns nothing renders the lean shape, which
  is the same answer a fresh install gets.
- **`enabled: null` is a third state, and readers of a values file expect two.** The
  comment in `values.yaml` has to earn that, and the helper's name has to say it. A
  reviewer who reads `enabled: null` as "off" is not wrong about a fresh install — only
  about an upgrade.
- **A tier expires by test, not by ceremony.** When the declarative pipeline runtime
  lands, `refuse_placeholder_deploy` stops refusing and the bidirectional test fails
  until the tier is removed. That is the intended way to find out; it is also the only
  way — nothing else notices.
- **`SUPPORT.md` becomes load-bearing.** It is prose today and a parsed contract after
  this change. The parse is one sentence's list of names; a rewrite of that paragraph
  that keeps the names is fine, and one that drops a name fails the test rather than
  quietly widening what the product claims to support.
