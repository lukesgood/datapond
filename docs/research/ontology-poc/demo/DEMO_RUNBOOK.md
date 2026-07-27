# Concept-Expansion Demo Runbook (design-partner demo)

Purpose: show, live, the one case where concept expansion demonstrably pays —
**jargon/code retrieval** (medical billing here) — plus the governance angle
(concept-level PII tags). This is the demo-armed validation asset for the gate in
`docs/CONCEPT_RECONFIRMATION.md` §5.2.

> **Before every demo:** `cd backend && python3 ../docs/research/ontology-poc/demo/verify_demo.py`
> — asserts each §3 query fires its intended concept (alias gaps are silent otherwise).

## 0. Prerequisites

- Environment restarted per `docs/OPERATIONS_PAUSE.md` (Aurora first, then the node)
  — or any dev deployment. Admin token in `$TOK` (`/api/auth/login`).
- Ontology capability ON for the release:
  `helm upgrade ... --reset-then-reuse-values --set ontology.enabled=true`
  (renders `FEATURE_ONTOLOGY=true`; the concept store self-creates at startup).
- Verify: `GET /api/capabilities` → `"ontology": true`, and the Knowledge search
  bar shows the **Concepts** toggle.

```bash
BASE=https://datapond.csg.fitcloud.co.kr
AUTH="Authorization: Bearer $TOK"
```

## 1. Import the jargon concept pack

```bash
curl -sS -X POST "$BASE/api/ai/concepts/import" -H "$AUTH" -H "Content-Type: application/json" \
  --data @medical_billing_concepts.json
# → {"ok": true, "imported": 10}
curl -sS "$BASE/api/ai/concepts" -H "$AUTH" | head
```

## 2. Seed a demo collection (code-heavy chunks)

Create collection `billing-demo` in the Knowledge UI, then paste-ingest each doc
below as a separate ingest (source label = the title). The chunks intentionally
contain **codes only** — the plain-language vocabulary lives in the concept pack,
which is exactly the gap expansion bridges.

| source label | text |
|---|---|
| `form-ub04.md` | Form UB-04 (CMS-1450): submit within 90 days of discharge. Required for all facility claims. |
| `form-cms1500.md` | Form CMS-1500: submit within 60 days of the date of service. Required for professional claims. |
| `fee-99213.md` | Code 99213 reimburses $85 per encounter under the standard fee schedule. |
| `fee-99215.md` | Code 99215 reimburses $170 per encounter under the standard fee schedule. |
| `auth-policy.md` | Services on the precert list are denied when no approval is on file before the date of service. |
| `era-注.md` | The 835 file posts payments automatically; unmatched lines route to the manual work queue. |

## 3. The side-by-side moment

Ask each query twice in Knowledge → Search/RAG on `billing-demo`: once with the
**Concepts** toggle OFF, once ON.

| Query (plain language — never says the code) | Expect OFF | Expect ON |
|---|---|---|
| "Which claim form does a hospital use for an inpatient bill?" | misses or wrong form | **UB-04 chunk top** — trust bar shows `expanded via UB-04` |
| "What is the fee for a long complex consultation?" | 99213/99215 confusable | **99215** correct |
| "Do I need approval before scheduling this procedure?" | weak match | **precert chunk** via PriorAuthorization |
| "Where do electronic payment postings come from?" | weak match | **835/ERA chunk** |

Talking points while it runs:
- The delta is the PoC-measured case (+25% recall@1 on codes; ~0 on everyday
  synonyms — we say that out loud; honesty is the brand).
- Point at the **`expanded via …` chips**: the expansion is *inspectable*, not magic.
- Ask about the member: "Can the insured see their benefit statement?" → the
  **Member** concept fires with a **PII-tinted chip** — segue to concept-level
  governance (the durable value: PII tagging, access, lineage — not "better search").

## 4. Reset (after the demo)

```bash
# remove demo concepts (loop over names) and delete the billing-demo collection in the UI
for n in UB-04 CMS-1500 CPT-99213 CPT-99215 EOB ERA PriorAuthorization Deductible Member NPI; do
  curl -sS -X DELETE "$BASE/api/ai/concepts/$n" -H "$AUTH" >/dev/null
done
```
Re-pause the environment per `docs/OPERATIONS_PAUSE.md` if the demo machine is the
paused single-node.

## What NOT to demo

Entity graphs, relation extraction, GraphRAG — not built (demand-gated). If asked:
"that's exactly the conversation we want to have" → capture it as the partner
pulling Phase 1 (the strongest demand signal the gate defines).
