# Ontology PoC — reproducible validation harnesses

Harnesses behind `docs/ONTOLOGY_FEASIBILITY_REPORT.md`. Each runs against Amazon Bedrock
(Claude Haiku 4.5 / Sonnet 4.6 for extraction/consolidation, Titan Text v2 for embeddings) —
DataPond's actual model backends. Requires AWS creds with `bedrock:InvokeModel` in us-east-1.

| Script | Experiment |
|---|---|
| `ont_bootstrap.py` | 1 — T-Box concept/schema bootstrap (map→reduce) + eval vs gold |
| `abox_resolution.py` | 2 — entity extraction + resolution + false-merge eval (hard negatives) |
| `blocking_poc.py` | 3 — embedding vs multi-key blocking (pair recall / reduction ratio) |
| `end2end_expansion.py` | 4a — concept-expansion retrieval value (common synonyms) |
| `jargon_expansion.py` | 4b — concept-expansion value on jargon/codes |
| `multidomain.py` | 5 — cross-domain generalization (insurance/legal/healthcare) |

Corpora + hand-built gold are inline in each script. `emb_cache.json` (regenerable) is not
committed. Run: `python3 <script>.py`.

NOTE: research/decision artifacts — NOT shipped product code.
