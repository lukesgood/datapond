#!/usr/bin/env python3
"""
LLM-assisted ontology bootstrap — design PoC + validation experiment.

Pipeline (product design):
  A) MAP    : per-document concept/alias/relation extraction (LLM, structured JSON)
  B) REDUCE : cross-document consolidation -> canonical ontology (merge synonyms,
              build is-a taxonomy, dedupe relations, flag PII)  [LLM]
  (product) C) human curation via UI — this experiment measures how close (B) is to a
              hand-built GOLD, i.e. the *curation burden* left for the human.

Model: Claude Haiku 4.5 on Bedrock (DataPond's default backend) — product-realistic.
"""
import json, subprocess, tempfile, os, re, sys

MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "us-east-1"

# ── Corpus: 5 short insurance-domain docs with deliberate synonym variety ──────
CORPUS = {
 "auto_summary.md": """Auto Policy Summary. Your car insurance provides coverage for collision and
liability. The insured must pay a monthly premium of $120. A deductible of $500 applies to each
collision claim. Coverage limits are $50,000 per accident. The policy is renewed annually unless
cancelled. Contact your agent for changes.""",
 "claims_procedure.md": """Claims Procedure. To file a claim, the policyholder submits a claim form
within 30 days. The claim is filed against the active policy. An adjuster performs underwriting review
to assess the loss. Approved payouts are sent to the policyholder, or to the named beneficiary for
life insurance claims.""",
 "glossary.md": """Glossary. Premium: the payment made for insurance coverage. Deductible (also called
the excess): the amount the insured pays before coverage applies. Beneficiary: the person who receives
the payout. Coverage: the protection provided by the policy against specified risks.""",
 "home_policy.md": """Homeowners Policy. This property insurance covers fire and theft. The homeowner
(policyholder) pays an annual premium. An excess of $1,000 applies per claim. The cover includes the
dwelling and contents. Renewal notices are sent 30 days before expiry.""",
 "agent_email.md": """From your broker: Your auto policy renewal is due next month. I've also attached a
life insurance quote — remember to name a beneficiary on any life policy. As your agent I can bundle
home and auto coverage for a lower premium.""",
}

# ── GOLD ontology (hand-built reference) ──────────────────────────────────────
# canonical name -> {aliases, parent(is-a), pii}
GOLD_CONCEPTS = {
 "Contract":     {"aliases": ["agreement"], "parent": None, "pii": False},
 "Policy":       {"aliases": ["insurance policy"], "parent": "Contract", "pii": False},
 "AutoPolicy":   {"aliases": ["auto insurance", "car insurance", "motor policy", "auto policy"], "parent": "Policy", "pii": False},
 "HomePolicy":   {"aliases": ["home insurance", "homeowners policy", "property insurance", "home policy"], "parent": "Policy", "pii": False},
 "LifePolicy":   {"aliases": ["life insurance", "life policy"], "parent": "Policy", "pii": False},
 "Policyholder": {"aliases": ["insured", "policy holder", "homeowner", "customer"], "parent": None, "pii": True},
 "Beneficiary":  {"aliases": [], "parent": None, "pii": True},
 "Premium":      {"aliases": ["insurance payment", "payment"], "parent": None, "pii": False},
 "Deductible":   {"aliases": ["excess"], "parent": None, "pii": False},
 "Coverage":     {"aliases": ["cover", "insured amount", "coverage limit"], "parent": None, "pii": False},
 "Claim":        {"aliases": ["insurance claim"], "parent": None, "pii": False},
 "Underwriting": {"aliases": ["underwriter assessment", "adjuster review"], "parent": None, "pii": False},
 "Agent":        {"aliases": ["insurance agent", "broker"], "parent": None, "pii": False},
 "Renewal":      {"aliases": ["policy renewal"], "parent": None, "pii": False},
}
# relations as (subject, object) canonical pairs (predicate checked qualitatively)
GOLD_RELATIONS = {
 ("Policyholder", "Policy"), ("Policyholder", "Premium"), ("Policy", "Coverage"),
 ("Policy", "Deductible"), ("Claim", "Policy"), ("Beneficiary", "Claim"),
 ("Agent", "Policy"), ("Premium", "Policy"), ("Policy", "Renewal"),
}

SONNET = "us.anthropic.claude-sonnet-4-6"

def bedrock(prompt, max_tokens=1500, model=None):
    body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    model = model or MODEL
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(body, f); bpath = f.name
    out = bpath + ".out"
    subprocess.run(["aws", "bedrock-runtime", "invoke-model", "--model-id", model,
                    "--body", "fileb://" + bpath, "--cli-binary-format", "raw-in-base64-out",
                    "--region", REGION, out], check=True, capture_output=True)
    d = json.load(open(out)); os.unlink(bpath); os.unlink(out)
    return d["content"][0]["text"]

def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"[\{\[].*[\}\]]", text, re.S)
    return json.loads(m.group(0) if m else text)

MAP_PROMPT = """You are extracting a domain ontology from a document. Return STRICT JSON only.
From the document, extract:
- "concepts": list of {{"name": canonical PascalCase noun concept (a class/type, not an instance),
    "aliases": [surface terms/synonyms/abbreviations seen for it],
    "parent_hint": a more general concept name if this is clearly a subtype, else null,
    "pii": true if the concept denotes a person/personal identifier}}
- "relations": list of {{"subject": concept, "predicate": short verb, "object": concept}}
Only concepts that are domain types. No prose.

DOCUMENT ({name}):
{doc}

JSON:"""

REDUCE_PROMPT = """Consolidate candidate ontology fragments into ONE CONCISE canonical domain ontology.
RULES:
- Produce ~12-18 CORE domain TYPES only. A concept is a reusable class/type — not an instance, an
  attribute value, or a one-off noun.
- FOLD fine-grained variants into their parent as aliases/narrower terms; do NOT list them as separate
  concepts. Examples: CollisionCoverage/LiabilityCoverage -> Coverage; Fire/Theft/Peril -> fold away or
  -> Risk; Dwelling/Contents/Property -> fold into Coverage; Adjuster/UnderwritingReview -> Underwriting;
  Payout -> Claim; Accident/Loss -> fold away; Quote -> fold away.
- Build the is-a taxonomy via "parent": AutoPolicy/HomePolicy/LifePolicy is-a Policy is-a Contract.
- RELATIONS: connect TWO core concepts using a predicate from EXACTLY this closed set:
  [holds, pays, has, covers, filedAgainst, receives, sells, paidFor, hasRenewal, assesses].
  Output the minimal set of TYPE-LEVEL relations (no instance relations, no duplicates, both endpoints
  must be core concepts you listed).
- Flag pii=true for person concepts (Policyholder, Beneficiary).
Return STRICT JSON only:
{{"concepts":[{{"name":PascalCase,"aliases":[...],"parent":<concept name or null>,"pii":bool}}],
 "relations":[{{"subject":concept,"predicate":verb,"object":concept}}]}}

CANDIDATES (JSON):
{cands}

Concise consolidated ontology JSON:"""

def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def run_bootstrap():
    print("== STAGE A: per-document extraction (map) ==")
    cands = []
    for name, doc in CORPUS.items():
        try:
            frag = parse_json(bedrock(MAP_PROMPT.format(name=name, doc=doc)))
            cands.append({"doc": name, **frag})
            print(f"  {name}: {len(frag.get('concepts',[]))} concepts, {len(frag.get('relations',[]))} relations")
        except Exception as e:
            print(f"  {name}: FAILED {e}")
    print("== STAGE B: consolidation (reduce) ==")
    draft = parse_json(bedrock(REDUCE_PROMPT.format(cands=json.dumps(cands, ensure_ascii=False)), max_tokens=2500, model=SONNET))
    json.dump(draft, open("draft_ontology.json", "w"), ensure_ascii=False, indent=2)
    print(f"  draft: {len(draft.get('concepts',[]))} concepts, {len(draft.get('relations',[]))} relations -> draft_ontology.json")
    return draft

def gold_match(name):
    """Return canonical gold concept whose name/alias matches `name`, else None."""
    n = norm(name)
    for canon, meta in GOLD_CONCEPTS.items():
        if n == norm(canon) or n in {norm(a) for a in meta["aliases"]}:
            return canon
    return None

def evaluate(draft):
    dcs = draft.get("concepts", [])
    # map each draft concept -> gold canonical (by name or any alias)
    draft_to_gold = {}
    for c in dcs:
        g = gold_match(c["name"]) or next((gold_match(a) for a in c.get("aliases", []) if gold_match(a)), None)
        draft_to_gold[c["name"]] = g
    matched_gold = {g for g in draft_to_gold.values() if g}
    spurious = [c["name"] for c, g in [(c, draft_to_gold[c["name"]]) for c in dcs] if not g]
    missed = [g for g in GOLD_CONCEPTS if g not in matched_gold]

    c_recall = len(matched_gold) / len(GOLD_CONCEPTS)
    c_prec = (len(dcs) - len(spurious)) / len(dcs) if dcs else 0

    # taxonomy edges (child->parent) mapped to gold canonicals
    gold_tax = {(c, m["parent"]) for c, m in GOLD_CONCEPTS.items() if m["parent"]}
    draft_tax = set()
    for c in dcs:
        cg = draft_to_gold.get(c["name"]); pg = gold_match(c.get("parent") or "")
        if cg and pg: draft_tax.add((cg, pg))
    tax_ok = draft_tax & gold_tax
    tax_prec = len(tax_ok) / len(draft_tax) if draft_tax else 0
    tax_recall = len(tax_ok) / len(gold_tax) if gold_tax else 0

    # relation concept-pairs
    draft_rel = set()
    for r in draft.get("relations", []):
        sg, og = gold_match(r.get("subject", "")), gold_match(r.get("object", ""))
        if sg and og: draft_rel.add((sg, og))
    rel_ok = draft_rel & GOLD_RELATIONS
    rel_recall = len(rel_ok) / len(GOLD_RELATIONS)
    rel_prec = len(rel_ok) / len(draft_rel) if draft_rel else 0

    # PII flag accuracy on matched person concepts
    pii_gold = {g for g, m in GOLD_CONCEPTS.items() if m["pii"]}
    pii_draft = {draft_to_gold[c["name"]] for c in dcs if c.get("pii") and draft_to_gold.get(c["name"])}
    pii_ok = pii_draft & pii_gold

    # curation-burden proxy: ops to reach gold from draft
    ops = len(missed) + len(spurious) + (len(gold_tax) - len(tax_ok)) + len(draft_tax - gold_tax) + (len(GOLD_RELATIONS) - len(rel_ok))
    correct = len(matched_gold) + len(tax_ok) + len(rel_ok)
    usable = correct / (correct + ops) if (correct + ops) else 0

    print("\n" + "=" * 64)
    print("VALIDATION RESULTS (draft LLM ontology vs hand-built GOLD)")
    print("=" * 64)
    print(f"Concepts     recall {c_recall:.2f}  precision {c_prec:.2f}   "
          f"({len(matched_gold)}/{len(GOLD_CONCEPTS)} gold found, {len(spurious)} spurious)")
    print(f"Taxonomy     recall {tax_recall:.2f}  precision {tax_prec:.2f}   "
          f"(is-a edges {len(tax_ok)}/{len(gold_tax)} correct)")
    print(f"Relations    recall {rel_recall:.2f}  precision {rel_prec:.2f}   "
          f"(concept-pairs {len(rel_ok)}/{len(GOLD_RELATIONS)})")
    print(f"PII flags    {len(pii_ok)}/{len(pii_gold)} person concepts correctly flagged")
    print(f"Curation burden proxy: {usable:.0%} of the graph usable as-is  "
          f"({ops} edits to reach gold)")
    print(f"  missed concepts : {missed}")
    print(f"  spurious        : {spurious}")
    print(f"  bad taxonomy    : {sorted(draft_tax - gold_tax)}")
    # pre-registered success bar
    bar = dict(c_recall=(c_recall,0.80), c_prec=(c_prec,0.70), tax_prec=(tax_prec,0.70),
               rel_recall=(rel_recall,0.60), usable=(usable,0.70))
    print("\nPre-registered success bar:")
    passed = 0
    for k,(v,t) in bar.items():
        ok = v >= t; passed += ok
        print(f"  {k:10s} {v:.2f} >= {t:.2f}  {'PASS' if ok else 'FAIL'}")
    print(f"\nVERDICT: {passed}/{len(bar)} criteria met -> "
          f"{'FEASIBLE (self-serve draft + light curation)' if passed >= 4 else 'NEEDS ITERATION'}")

if __name__ == "__main__":
    draft = json.load(open("draft_ontology.json")) if "--eval-only" in sys.argv else run_bootstrap()
    evaluate(draft)
