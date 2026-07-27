#!/usr/bin/env python3
"""Pre-demo check: every runbook query must fire its intended concept.

Run from backend/ (needs the app on the path):
    cd backend && python3 ../docs/research/ontology-poc/demo/verify_demo.py
Catches alias gaps BEFORE a design-partner demo — the PoC showed the lexical
trigger is quality-sensitive, so never demo unverified pack edits.
"""
import json
import pathlib
import sys

sys.path.insert(0, ".")
from app.api.ontology import expand_query_text  # noqa: E402

HERE = pathlib.Path(__file__).parent
pack = json.loads((HERE / "medical_billing_concepts.json").read_text())
concepts = [{"name": c["name"], "pii": c.get("pii", False), "terms": c.get("aliases", [])}
            for c in pack["concepts"]]

# Mirror of the runbook §3 table (query → concept that must fire).
QUERIES = [
    ("Which claim form does a hospital use for an inpatient bill?", "UB-04"),
    ("What is the fee for a long complex consultation?", "CPT-99215"),
    ("Do I need approval before scheduling this procedure?", "PriorAuthorization"),
    ("Where do electronic payment postings come from?", "ERA"),
    ("Can the insured see their benefit statement?", "Member"),
]

ok = True
for q, want in QUERIES:
    _, matched = expand_query_text(q, concepts)
    names = [m["name"] for m in matched]
    hit = want in names
    ok &= hit
    print(f"{'PASS' if hit else 'FAIL':4s} {q[:56]:56s} -> {names}")

print("\nALL PASS — demo-ready" if ok else "\nFAIL — fix pack aliases before demoing")
sys.exit(0 if ok else 1)
