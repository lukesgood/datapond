#!/usr/bin/env python3
"""
End-to-end VALUE experiment: does ontology-driven concept expansion improve retrieval?
Baseline = plain vector search (what DataPond does today: embed query -> cosine top-k).
Expanded = expand the query with aliases of matched concepts from the AUTO-BUILT ontology
           (draft_ontology.json from ont_bootstrap), then embed -> retrieve.
Queries deliberately use DIFFERENT terminology than the relevant chunk (synonym/jargon gap).
Metric: recall@k + gold rank. Embeddings: Amazon Titan v2 on Bedrock (DataPond's embed backend).
"""
import json, subprocess, tempfile, os, re, math

TITAN="amazon.titan-embed-text-v2:0"; REGION="us-east-1"; CACHE="emb_cache.json"

CHUNKS={
 "c1_deductible":"A deductible of $500 applies to each collision claim before coverage begins.",
 "c2_limit":"Coverage limits are $50,000 per accident for liability protection.",
 "c3_renewal":"The policy is renewed annually; renewal notices are sent 30 days before expiry.",
 "c4_premium":"The insured pays a monthly premium of $120 for the auto policy.",
 "c5_beneficiary":"For life insurance, approved payouts are sent to the named beneficiary.",
 "c6_claimproc":"To file a claim, the policyholder submits a claim form within 30 days.",
 "c7_homeexcess":"For the homeowners policy, an excess of $1,000 applies per home claim.",
 "c8_underwriting":"An adjuster performs an underwriting review to assess the loss.",
 "c9_bundle":"You can bundle home and auto coverage together for a lower premium.",
 "c10_peril":"The property insurance covers fire and theft on the dwelling.",
 "c11_agent":"Contact your insurance agent or broker to make changes to your policy.",
 "c12_autocollision":"Car insurance provides coverage for collision and liability damage.",
}
# query -> gold chunk (query worded with a TERMINOLOGY GAP vs the chunk)
QUERIES=[
 ("What is the excess for a collision claim?","c1_deductible"),     # excess->deductible
 ("How much cover do I get per accident?","c2_limit"),              # cover->coverage limit
 ("Who receives the money for a life policy payout?","c5_beneficiary"),
 ("How do I renew my insurance each year?","c3_renewal"),
 ("What does the assessor do when I make a claim?","c8_underwriting"),# assessor->adjuster/underwriting
 ("What perils are covered on my house?","c10_peril"),              # perils->fire/theft, house->property
 ("How much do I pay each month?","c4_premium"),                    # pay each month->premium
 ("Who do I talk to to change my plan?","c11_agent"),               # ->agent/broker
 ("What protection do I have for a car crash?","c12_autocollision"),# protection->coverage, crash->collision
]

def embed(text):
    body={"inputText":text}
    with tempfile.NamedTemporaryFile("w",suffix=".json",delete=False) as f: json.dump(body,f); bp=f.name
    out=bp+".out"
    subprocess.run(["aws","bedrock-runtime","invoke-model","--model-id",TITAN,"--body","fileb://"+bp,
                    "--cli-binary-format","raw-in-base64-out","--region",REGION,out],check=True,capture_output=True)
    d=json.load(open(out)); os.unlink(bp); os.unlink(out); return d["embedding"]
def cos(a,b):
    dot=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na and nb else 0.0
def norm(s): return re.sub(r"[^a-z0-9]"," ",s.lower()).split()

# ── concept expansion from the AUTO-BUILT ontology ──
ONT=json.load(open("draft_ontology.json"))
TERMSETS=[]  # each concept -> set of its terms (name+aliases), all lowercased phrases
for c in ONT["concepts"]:
    terms={c["name"]}|set(c.get("aliases",[]))
    TERMSETS.append({t.lower() for t in terms if t})
def expand(query):
    ql=" "+" ".join(norm(query))+" "
    add=set()
    for terms in TERMSETS:
        # concept matches the query if any of its terms (as a token/phrase) appears
        if any((" "+re.sub(r"[^a-z0-9]"," ",t.lower()).strip()+" ") in ql for t in terms if t):
            add|=terms
    add={a for a in add if re.sub(r"[^a-z0-9]","",a) and (" "+a+" ") not in ql}
    return query+((" "+" ".join(sorted(add))) if add else ""), sorted(add)

if __name__=="__main__":
    cache=json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    texts=list(CHUNKS.values())+[q for q,_ in QUERIES]+[expand(q)[0] for q,_ in QUERIES]
    for t in texts:
        if t not in cache: cache[t]=embed(t)
    json.dump(cache,open(CACHE,"w"))
    cids=list(CHUNKS); C=[cache[CHUNKS[c]] for c in cids]

    def rank(qemb):
        return [cids[i] for i in sorted(range(len(cids)),key=lambda i:-cos(qemb,C[i]))]
    def recall_at(ranks,gold,k): return int(gold in ranks[:k])

    Ks=(1,3,5); agg={m:{k:0 for k in Ks} for m in ("base","exp")}
    print(f"{'query':46s} {'gold rank':>9} {'exp rank':>8}  expansion terms")
    print("-"*100)
    for q,gold in QUERIES:
        rb=rank(cache[q]); eq,terms=expand(q); re_=rank(cache[eq])
        gr=rb.index(gold)+1; er=re_.index(gold)+1
        for k in Ks: agg["base"][k]+=recall_at(rb,gold,k); agg["exp"][k]+=recall_at(re_,gold,k)
        mark=" ↑" if er<gr else (" ↓" if er>gr else "")
        print(f"{q[:46]:46s} {gr:>9} {er:>8}{mark}  {', '.join(terms[:6])}")
    n=len(QUERIES)
    print("\n"+"="*60)
    print(f"{'':10s}"+"".join(f"recall@{k:<6}" for k in Ks))
    for m,lbl in (("base","baseline"),("exp","expanded")):
        print(f"{lbl:10s}"+"".join(f"{agg[m][k]/n:<9.2f}" for k in Ks))
    print("\ndelta     "+"".join(f"{(agg['exp'][k]-agg['base'][k])/n:+<9.2f}" for k in Ks))
    # mean reciprocal rank
    mrr={m:0.0 for m in ("base","exp")}
    for q,gold in QUERIES:
        mrr["base"]+=1/(rank(cache[q]).index(gold)+1)
        mrr["exp"]+=1/(rank(cache[expand(q)[0]]).index(gold)+1)
    print(f"\nMRR   baseline {mrr['base']/n:.3f}   expanded {mrr['exp']/n:.3f}   "
          f"delta {(mrr['exp']-mrr['base'])/n:+.3f}")
