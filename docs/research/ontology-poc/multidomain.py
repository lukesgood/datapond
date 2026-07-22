#!/usr/bin/env python3
"""
Generalization experiment: does the T-Box bootstrap work across DOMAINS with ONE
domain-agnostic pipeline? Runs the same map(Haiku)+reduce(Sonnet) pipeline with a
GENERIC reduce prompt (no domain-specific examples) on 3 domains vs hand-built gold.
"""
import json, subprocess, tempfile, os, re
HAIKU="us.anthropic.claude-haiku-4-5-20251001-v1:0"; SONNET="us.anthropic.claude-sonnet-4-6"; REGION="us-east-1"

def bedrock(prompt, model, mx=2000):
    b={"anthropic_version":"bedrock-2023-05-31","max_tokens":mx,"messages":[{"role":"user","content":prompt}]}
    with tempfile.NamedTemporaryFile("w",suffix=".json",delete=False) as f: json.dump(b,f); p=f.name
    o=p+".out"; subprocess.run(["aws","bedrock-runtime","invoke-model","--model-id",model,"--body","fileb://"+p,
      "--cli-binary-format","raw-in-base64-out","--region",REGION,o],check=True,capture_output=True)
    d=json.load(open(o)); os.unlink(p); os.unlink(o); return d["content"][0]["text"]
def pj(t):
    t=re.sub(r"^```(?:json)?|```$","",t.strip(),flags=re.M).strip()
    m=re.search(r"[\{\[].*[\}\]]",t,re.S); return json.loads(m.group(0) if m else t)
def norm(s): return re.sub(r"[^a-z0-9]","",(s or "").lower())

MAP="""Extract a domain ontology from the document. STRICT JSON only:
- "concepts":[{{"name":PascalCase class/type (not an instance),"aliases":[surface terms/synonyms seen],
   "parent_hint":more-general concept or null,"pii":true if a person/personal identifier}}]
- "relations":[{{"subject":concept,"predicate":short verb,"object":concept}}]
DOCUMENT ({name}): {doc}
JSON:"""
REDUCE="""Consolidate candidate ontology fragments into ONE CONCISE canonical domain ontology. RULES:
- ~12-18 CORE domain TYPES only. A concept is a reusable class/type, NOT an instance, attribute value,
  quantity, or one-off noun. Fold fine-grained variants/examples into their parent as aliases; do not
  list them separately.
- Build is-a taxonomy via "parent" where a concept is clearly a subtype.
- RELATIONS: connect TWO core concepts with a short verb predicate; reuse a small consistent predicate
  set; minimal type-level relations only (both endpoints must be listed concepts).
- pii=true for person / personal-identifier concepts.
STRICT JSON: {{"concepts":[{{"name","aliases":[...],"parent":<name|null>,"pii":bool}}],"relations":[{{"subject","predicate","object"}}]}}
CANDIDATES: {cands}
Concise ontology JSON:"""

DOMAINS={
 "LEGAL": {
  "corpus":{
   "l1":"This Agreement is between the Buyer (the client) and the Seller (the vendor). The purchaser agrees to the payment terms in Section 3.",
   "l2":"Clause 7 Confidentiality: each party has a duty to protect confidential information. The non-disclosure obligation survives termination.",
   "l3":"The vendor shall provide the goods per the deliverable schedule. Warranty: the supplier guarantees the goods for 12 months. Liability is capped at the contract value.",
   "l4":"This contract is governed by the laws of Delaware. Any breach or default lets the non-breaching party terminate. Effective date: Jan 1. Signed by the authorized signatory."},
  "gold_concepts":{
   "Contract":{"aliases":["agreement"],"parent":None,"pii":False},
   "Party":{"aliases":[],"parent":None,"pii":False},
   "Buyer":{"aliases":["purchaser","client"],"parent":"Party","pii":False},
   "Seller":{"aliases":["vendor","supplier"],"parent":"Party","pii":False},
   "Clause":{"aliases":["provision","section"],"parent":None,"pii":False},
   "Obligation":{"aliases":["duty"],"parent":None,"pii":False},
   "PaymentTerm":{"aliases":["payment terms","consideration"],"parent":None,"pii":False},
   "Deliverable":{"aliases":["goods","services"],"parent":None,"pii":False},
   "ConfidentialityClause":{"aliases":["confidentiality","non-disclosure","nda"],"parent":"Clause","pii":False},
   "TerminationClause":{"aliases":["termination"],"parent":"Clause","pii":False},
   "Warranty":{"aliases":["guarantee"],"parent":None,"pii":False},
   "Liability":{"aliases":[],"parent":None,"pii":False},
   "GoverningLaw":{"aliases":["jurisdiction"],"parent":None,"pii":False},
   "Breach":{"aliases":["default","violation"],"parent":None,"pii":False},
   "Signatory":{"aliases":["signer"],"parent":"Party","pii":True}},
  "gold_relations":{("Party","Contract"),("Contract","Clause"),("Clause","Obligation"),("Party","Obligation"),
   ("Buyer","PaymentTerm"),("Seller","Deliverable"),("Breach","Clause"),("Contract","GoverningLaw"),("Signatory","Contract")}},

 "HEALTHCARE": {
  "corpus":{
   "h1":"The patient presented with chest pain and shortness of breath, both symptoms. The physician recorded a diagnosis of myocardial infarction in the patient's medical record.",
   "h2":"Providers on the care team include physicians (doctors) and nurses. The doctor ordered a treatment for the patient.",
   "h3":"Treatment includes aspirin, a medication, at a dosage of 81mg daily. The nurse documented a penicillin allergy in the patient's chart.",
   "h4":"During the encounter, the nurse recorded vital signs such as blood pressure and heart rate. A lab test measured troponin to confirm the condition.",
   "h5":"A cardiac procedure was performed at a later visit. Afterward the physician updated the diagnosis and the medical record.",
   "h6":"The patient's condition improved after treatment. A follow-up appointment was scheduled and the provider reviewed the medications and dosage."},
  "gold_concepts":{
   "Patient":{"aliases":[],"parent":None,"pii":True},
   "Provider":{"aliases":["clinician"],"parent":None,"pii":True},
   "Physician":{"aliases":["doctor"],"parent":"Provider","pii":True},
   "Nurse":{"aliases":[],"parent":"Provider","pii":True},
   "Diagnosis":{"aliases":["dx"],"parent":None,"pii":False},
   "Condition":{"aliases":["disease","disorder","illness"],"parent":None,"pii":False},
   "Symptom":{"aliases":["sign"],"parent":None,"pii":False},
   "Treatment":{"aliases":["therapy"],"parent":None,"pii":False},
   "Medication":{"aliases":["drug","prescription"],"parent":None,"pii":False},
   "Dosage":{"aliases":["dose"],"parent":None,"pii":False},
   "Procedure":{"aliases":["operation"],"parent":None,"pii":False},
   "LabTest":{"aliases":["lab","test"],"parent":None,"pii":False},
   "Allergy":{"aliases":[],"parent":None,"pii":False},
   "Encounter":{"aliases":["visit","appointment"],"parent":None,"pii":False},
   "VitalSign":{"aliases":["vitals"],"parent":None,"pii":False},
   "MedicalRecord":{"aliases":["chart","ehr"],"parent":None,"pii":True}},
  "gold_relations":{("Patient","Diagnosis"),("Provider","Patient"),("Physician","Patient"),("Treatment","Condition"),
   ("Medication","Condition"),("Patient","Allergy"),("Procedure","Encounter"),("LabTest","Condition"),("Patient","Encounter")}},
}

def run_domain(name, D):
    print(f"\n########## DOMAIN: {name} ##########")
    G=D["gold_concepts"]; GR=D["gold_relations"]
    GN={e:{norm(e)}|{norm(a) for a in m["aliases"]} for e,m in G.items()}
    def gmatch(x):
        n=norm(x)
        for e,f in GN.items():
            if n in f: return e
        return None
    cands=[]
    for nm,doc in D["corpus"].items():
        try:
            fr=pj(bedrock(MAP.format(name=nm,doc=doc),HAIKU)); cands.append({"doc":nm,**fr})
        except Exception as e: print("  map fail",nm,e)
    draft=pj(bedrock(REDUCE.format(cands=json.dumps(cands,ensure_ascii=False)),SONNET))
    dcs=draft.get("concepts",[])
    d2g={c["name"]:(gmatch(c["name"]) or next((gmatch(a) for a in c.get("aliases",[]) if gmatch(a)),None)) for c in dcs}
    matched={g for g in d2g.values() if g}; spur=[n for n,g in d2g.items() if not g]
    cr=len(matched)/len(G); cp=(len(dcs)-len(spur))/len(dcs) if dcs else 0
    gtax={(c,m["parent"]) for c,m in G.items() if m["parent"]}
    dtax={(d2g[c["name"]],gmatch(c.get("parent") or "")) for c in dcs if d2g[c["name"]] and gmatch(c.get("parent") or "")}
    tok=dtax&gtax; tp_=len(tok)/len(dtax) if dtax else 0; tr_=len(tok)/len(gtax) if gtax else 0
    drel={(gmatch(r.get("subject","")),gmatch(r.get("object",""))) for r in draft.get("relations",[])}
    drel={p for p in drel if all(p)}; rok=drel&GR; rr_=len(rok)/len(GR); rp_=len(rok)/len(drel) if drel else 0
    pg={g for g,m in G.items() if m["pii"]}; pd={d2g[c["name"]] for c in dcs if c.get("pii") and d2g.get(c["name"])}
    ops=len(set(G)-matched)+len(spur)+(len(gtax)-len(tok))+len(dtax-gtax)+(len(GR)-len(rok))
    corr=len(matched)+len(tok)+len(rok); usable=corr/(corr+ops) if corr+ops else 0
    print(f"  Concepts  recall {cr:.2f} prec {cp:.2f} ({len(matched)}/{len(G)}, {len(spur)} spurious)")
    print(f"  Taxonomy  recall {tr_:.2f} prec {tp_:.2f} ({len(tok)}/{len(gtax)})")
    print(f"  Relations recall {rr_:.2f} prec {rp_:.2f} ({len(rok)}/{len(GR)})")
    print(f"  PII {len(pd&pg)}/{len(pg)}   usable-as-is {usable:.0%}   spurious={spur}")
    bar={"c_recall":(cr,.80),"c_prec":(cp,.70),"tax_prec":(tp_,.70),"rel_recall":(rr_,.60),"usable":(usable,.70)}
    passed=sum(v>=t for v,t in bar.values())
    print(f"  BAR {passed}/5 -> {'FEASIBLE' if passed>=4 else 'NEEDS ITERATION'}")
    return dict(domain=name,**{k:round(v,2) for k,(v,_) in bar.items()},passed=passed)

if __name__=="__main__":
    res=[run_domain(n,D) for n,D in DOMAINS.items()]
    print("\n=== GENERALIZATION SUMMARY ===")
    print(f"{'domain':12s}{'c_rec':>7}{'c_prec':>7}{'tax_p':>7}{'rel_r':>7}{'usable':>7}{'bar':>5}")
    for r in res:
        print(f"{r['domain']:12s}{r['c_recall']:>7}{r['c_prec']:>7}{r['tax_prec']:>7}{r['rel_recall']:>7}{r['usable']:>7}{r['passed']:>4}/5")
    json.dump(res,open("multidomain_results.json","w"),indent=2)
