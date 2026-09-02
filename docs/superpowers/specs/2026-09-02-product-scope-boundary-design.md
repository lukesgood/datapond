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

## 2. Backend contract

`app/capabilities.py` gains one constant map and one key in its response:

```python
# What this release supports, beside what it merely runs. Absent means supported.
SUPPORT_TIERS = {
    "pipelines": "preview",
    "streaming": "experimental",
    "notebooks": "experimental",
    "experiments": "experimental",
    "lineage": "experimental",
}
```

`compute_capabilities(env)` returns its existing boolean map plus
`"support": dict(SUPPORT_TIERS)`. The module stays pure and dependency-free — a constant
dict, no I/O, no imports beyond `typing`.

Only non-supported capabilities are listed. A consumer reads "absent = supported", which
means adding a core capability later cannot silently acquire a tier, and removing a tier
is a deletion rather than an edit.

**Tests** (`backend/tests/test_capability_support_tiers.py`):

- every key in `SUPPORT_TIERS` is a real key of the boolean map — a tier for a
  capability that does not exist is a label nothing renders;
- no capability the module reports as unconditionally `True` carries a tier — the core
  cannot be marked experimental by a careless edit;
- the tier vocabulary is exactly `{"experimental", "preview"}`;
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

## 4. Defaults

`helm/datapond/values.yaml`: `airflow`, `spark`, `trino`, `polaris`, `risingwave`,
`openmetadata`, `jupyter`, `mlflow` → `enabled: false`.

Measured consequences, not guesses:

- `values-dev.yaml`, `values-onprem.yaml` and `values-quicktest.yaml` set the flags they
  want explicitly (quicktest sets seven of eight true, spark false). **Unaffected.**
- `values-foundation.yaml` and `values-prod-single.yaml` already set all eight false.
  **Unaffected.**
- `values-aws.yaml` sets none of them and therefore inherits. It becomes lean. This is
  the intent — the assessment names its inherited heavy defaults as a defect — and it
  changes what that profile renders, which §5 must fix in the documents that describe
  it.

Checked, rather than assumed: **no test asserts which workloads a profile renders.**
The `helm-lint` CI job (`.github/workflows/ci.yml`) renders seven profiles and asserts
only that each renders without error, and the `backend/tests/test_helm_*.py` files pin
security contexts, storage classes, duplicate keys and ordering — never a workload list.

So this change has no existing expectation to update, and equally nothing that would
catch it going wrong. The plan adds that check: a test that renders each profile and
pins which of the eight add-on Deployments appear, so the base profile's leanness and
the on-prem profile's fullness are both assertions rather than intentions.

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
| The flipped defaults render the profiles the design says they do | existing helm render tests, updated |
| Nothing else changed about who may reach these routes | the existing permission and route-inventory suites, unchanged and still green |

## Risks

- **A deployment that relied on base defaults loses its add-ons on upgrade.** Anyone who
  installed without a profile and without `--set` gets a lean release. That is the
  intended correction, and it is a breaking change for that population; it belongs in the
  release note, not hidden in a values diff.
- **A tier is a judgement, and judgements go stale.** `SUPPORT_TIERS` is a constant with
  no mechanism forcing it to match reality — if the declarative pipeline runtime is ever
  implemented, nothing fails when the `preview` tier stays. The tests pin its shape, not
  its truth. Stated here rather than discovered later.
