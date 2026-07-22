# LLM-Assisted Ontology — Feasibility & Value Validation Report

> **Status: research / decision record — NOT a shipped capability.** DataPond today ships
> pgvector RAG + LiteLLM gateway + PII masking + audit + RLS. Everything below is a set of
> PoC experiments run to decide whether an ontology / concept layer is worth building and
> whether it can be delivered *self-serve* (product, not consulting). All results are
> small-scale PoCs (n=1–2 domains, synthetic corpora, author-built gold, few runs) and must
> be read as directional signal, not proof.

## TL;DR (verdict)

The product-only pivot rests on one existential question: **can the product auto-build a
usable ontology + entity graph without a human services engagement?** Five experiments say:

- **Concept / alias layer — feasible and generalizes.** The LLM reliably extracts and
  consolidates the right concepts + synonyms across domains (recall 0.75–1.00).
- **Entity resolution — feasible and *safe*.** Context-aware LLM adjudication resolved
  entities at F1 1.00 with **zero dangerous false merges** on hard negatives (the regulated
  deal-killer). It scales via **multi-key blocking** (RR 0.95) — *not* naive embeddings.
- **Relations / graph edges — the persistent weak spot.** Type-level relation extraction was
  the weakest step in *every* domain (0.22–0.78, high variance). This is the part that needs
  curation.
- **Retrieval value is conditional, not general.** Concept expansion gave **~0 lift** where a
  modern embedder already knows the synonym, and **+25% recall@1** only for jargon / codes /
  out-of-vocabulary terms.

**Strategic consequence:** the ontology is a **governance + relationship + jargon-vertical**
play, **not** a "better search" play. Sell concept-level PII/access/lineage and relationship
queries and code-heavy verticals — do not pitch general retrieval-quality gains.

## Why this was tested

The commercialization analysis concluded DataPond's differentiator (governed, portable RAG,
deepened by an ontology) is also its most services-heavy part. For the business to survive on
*product* rather than consulting, the ontology must be **self-serve**: the product drafts it,
the user lightly curates. These experiments probe whether that is achievable and where it
breaks.

Models used (DataPond's actual backends, via Amazon Bedrock): **Claude Haiku 4.5** (extraction),
**Claude Sonnet 4.6** (consolidation / resolution), **Amazon Titan Text v2** (embeddings).

## Experiments & results

### 1. T-Box bootstrap — auto-build the concept/schema (insurance)
Map (per-doc extraction) → Reduce (cross-doc consolidation) → measure vs hand-built gold.
- Naive prompt: **1/5** criteria met (over-granular: 39% concept precision).
- With **granularity control + a controlled predicate vocabulary + a capable reduce model**:
  **5/5** — concepts recall 1.00 / precision 0.93, taxonomy 1.00, relations 0.89/0.67, PII 2/2,
  **93% of the graph usable as-is** (2 edits to reach gold).
- *Finding:* the first attempt failed; **one design iteration** moved it to a pass → the
  bottleneck is prompt/pipeline design, not a fundamental LLM limit.

### 2. A-Box adjudication — entity extraction + resolution (hard negatives)
Corpus seeded with traps: similar names that are **different** entities (Acme Corp vs Acme
Holdings; shared surnames).
- Extraction: 6/6 gold entities found.
- Baseline (normalized string): pairwise P 1.00 / R 0.68 — safe but incomplete.
- **Context-aware LLM: P 1.00 / R 1.00 / F1 1.00, and 0 false merges** — it kept every hard
  negative apart while merging true variants.
- *Finding:* the deal-killer (merging two different real entities) did **not** occur; the
  adjudication step is high-quality and safe on this probe.

### 3. Scaling — embedding blocking / candidate generation
O(N²) LLM adjudication doesn't scale → blocking must cheaply keep only plausible candidate
pairs at **high recall** (missed pairs = permanent false splits).
- **Pure semantic-embedding blocking is inadequate** for names/IDs — recall ≤ 0.72 (misses
  abbreviations/truncations like "Rob Brown"↔"R. Brown"). *A non-obvious, important correction.*
- **Multi-key blocking** (token + char-n-gram + ID/numeric normalization + embedding): **recall
  0.96, reduction ratio 0.95** (2278 pairs → ~104 candidates).
- Residual ~4% (bare first-name ↔ initial+surname) is a **coreference floor** — needs context,
  not surface signal.
- *Finding:* scaling is feasible with a **Splink-style multi-key blocker**, then LLM
  adjudication on survivors.

### 4. End-to-end value — does concept expansion improve retrieval?
Baseline (plain vector search) vs ontology-expanded queries, on terminology-mismatch queries.
- **Common synonyms:** baseline already recall@1 = 1.00 → expansion delta **0.00**. A strong
  embedder (Titan) already bridges everyday synonyms.
- **Jargon / codes** (medical billing codes, code-only chunks): baseline recall@1 **0.50** →
  expanded **0.75** (**+0.25**); expansion also exposed that the **concept-match trigger** itself
  needs fuzzy matching (one query under-fired).
- *Finding:* retrieval value is **conditional** — negligible for general synonyms, material for
  jargon/codes/OOV and confusable corpora.

### 5. Generalization — one pipeline across domains (legal, healthcare)
Same domain-agnostic pipeline on new domains.
- **Legal: 4/5** (concepts 1.00/0.89, relations 0.78) — generalizes well (relational domain).
- **Healthcare: 1/5 → 2/5** after giving a realistically-sized corpus; critically **taxonomy
  recall 0.00 → 1.00** once the corpus actually stated the hierarchy — confirming a **corpus-
  sparsity confound**, not a pipeline limit.
- **Relations weak in every domain** (0.22–0.78); **run-to-run variance is significant** (legal
  scored 4/5 then 3/5 unchanged).
- *Finding:* concepts+aliases generalize; **taxonomy is corpus-dependent; relations are the
  universal bottleneck; single-run metrics are noisy** and must be aggregated.

## Honest limitations (apply to all five)

- Small synthetic corpora (3–6 short docs), author-built gold → risk of "grading own homework."
- n = 1–2 domains; **single runs** (variance demonstrated in exp 5) — no confidence intervals.
- No **measured human curation time** (the real self-serve metric) — only an edit-count proxy.
- No **real-scale** run (millions of entities), noisy/multilingual data, or subtler ambiguity.
- PII "correctness" is gold-subjective (is a physician PII?) — cross-domain gold is contestable.

## What this means (synthesis)

1. **The self-serve auto-ontology is real for the CONCEPT layer** (extraction + aliases +
   PII), buildable across domains with light curation. The **RELATION/graph layer needs
   curation everywhere** → "self-serve concepts + curated relationships," not fully automatic.
2. **The ontology's value is not general retrieval.** Modern embeddings already handle everyday
   synonyms. Its durable value is **(a) concept-level governance** (PII/access/lineage),
   **(b) relationship / multi-hop queries** (GraphRAG), **(c) jargon-heavy regulated verticals**
   (medical codes, legal citations, financial instruments, part numbers) where expansion
   demonstrably lifts retrieval.
3. **Positioning correction:** lead with *governed concept layer* + *relationship queries* +
   *jargon-vertical concept expansion* — **not** "better search."

## Recommended next validation (before betting)

1. **Multi-run × multi-domain with a domain-expert gold and measured curation time** —
   replace single-run PoC metrics with aggregated estimates + real human-in-the-loop effort.
2. **Real-scale entity resolution** with a Splink-style multi-key blocker (exp 3 validated the
   design; integrate the library and test at 10⁴–10⁶ mentions).
3. **Relation extraction hardening** — the universal weak spot; evaluate schema-constrained /
   controlled-predicate extraction and human-review workflows.
4. **Jargon-vertical retrieval study** — quantify expansion lift on a real code-heavy corpus
   (the case where it pays), tying to a target vertical.

## Appendix — reproducible harnesses

All run against DataPond's real backends (Bedrock Haiku/Sonnet/Titan):

| File | Experiment |
|---|---|
| `ont_bootstrap.py` | 1 — T-Box concept/schema bootstrap + eval |
| `abox_resolution.py` | 2 — entity extraction + resolution + false-merge eval |
| `blocking_poc.py` | 3 — embedding vs multi-key blocking (recall / reduction ratio) |
| `end2end_expansion.py`, `jargon_expansion.py` | 4 — concept-expansion retrieval value |
| `multidomain.py` | 5 — cross-domain generalization |
