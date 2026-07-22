#!/usr/bin/env python3
"""
Scale architecture PoC — embedding BLOCKING / candidate generation for entity resolution.
Full O(N^2) LLM adjudication doesn't scale. Blocking uses a cheap signal (embeddings /
lexical) to keep only plausible candidate pairs, which the LLM then adjudicates.
Metrics that matter:
  - pair completeness (BLOCKING RECALL): fraction of true-duplicate pairs retained.
    Anything missed here becomes a permanent false SPLIT — must be ~1.0.
  - reduction ratio (RR): 1 - candidate_pairs/all_pairs. How much LLM work is saved.
Compares: embedding(cos>=t) vs lexical(token/char-ngram) vs hybrid(OR).
Embeddings: Amazon Titan Text v2 (1024-dim) on Bedrock — DataPond's actual embed backend.
"""
import json, subprocess, tempfile, os, re, itertools, math

TITAN = "amazon.titan-embed-text-v2:0"; REGION = "us-east-1"
CACHE = "emb_cache.json"

# ── Controlled entity set: canonical -> surface forms. Sibling hard-negatives are
#    SEPARATE entities that share tokens (blocking should surface them; LLM rejects). ──
ENTITIES = {
 "AcmeCorporation": ["Acme Corporation","Acme Corp","Acme Corp.","Acme"],
 "AcmeHoldings":    ["Acme Holdings","Acme Holdings LLC"],           # sibling of AcmeCorporation
 "GlobexInc":       ["Globex Inc","Globex Inc.","Globex"],
 "InitechLLC":      ["Initech","Initech LLC","Initech, LLC"],
 "InitechSystems":  ["Initech Systems","Initech Systems Inc"],       # sibling of InitechLLC
 "SorayaBank":      ["Soraya Bank","Soraya Bank N.A.","Soraya"],
 "UmbrellaCorp":    ["Umbrella Corporation","Umbrella Corp","Umbrella"],
 "WayneEnterprises":["Wayne Enterprises","Wayne Ent.","Wayne"],
 "StarkIndustries": ["Stark Industries","Stark Ind","Stark"],
 "HooliLLC":        ["Hooli","Hooli LLC"],
 "JohnASmith":      ["John A. Smith","John Smith","J. Smith","John"],
 "JaneSmith":       ["Jane Smith","Jane"],                           # shared surname w/ John
 "RobertBrown":     ["Robert Brown","Rob Brown","R. Brown","Bob Brown"],
 "RachelBrown":     ["Rachel Brown"],                                # shared surname w/ Robert
 "MariaGarcia":     ["Maria Garcia","M. Garcia","Maria"],
 "CarlosGarcia":    ["Carlos Garcia"],                               # shared surname
 "PriyaPatel":      ["Priya Patel","P. Patel","Priya"],
 "DavidKim":        ["David Kim","D. Kim","Dave Kim"],
 "PolicyP1001":     ["Policy P-1001","P-1001","policy #1001","P1001"],
 "PolicyP2002":     ["Policy P-2002","P-2002"],
 "PolicyH7":        ["Home Policy H-7","H-7","policy H7"],
 "ClaimC55":        ["Claim C-55","C-55","claim #55"],
 "ContosoLtd":      ["Contoso Ltd","Contoso Limited","Contoso"],
 "ContosoRetail":   ["Contoso Retail","Contoso Retail Inc"],         # sibling of ContosoLtd
 "FabrikamInc":     ["Fabrikam Inc","Fabrikam"],
}

def bedrock_embed(text):
    body={"inputText":text}
    with tempfile.NamedTemporaryFile("w",suffix=".json",delete=False) as f:
        json.dump(body,f); bp=f.name
    out=bp+".out"
    subprocess.run(["aws","bedrock-runtime","invoke-model","--model-id",TITAN,"--body","fileb://"+bp,
                    "--cli-binary-format","raw-in-base64-out","--region",REGION,out],
                   check=True,capture_output=True)
    d=json.load(open(out)); os.unlink(bp); os.unlink(out); return d["embedding"]

def cos(a,b):
    dot=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na and nb else 0.0

STOP={"inc","corp","llc","ltd","limited","na","the","of","co","policy","claim","corporation","ent","ind"}
def toks(s): return {t for t in re.findall(r"[a-z0-9]+",s.lower()) if t not in STOP}
def char3(s):
    s=re.sub(r"[^a-z0-9]","",s.lower()); return {s[i:i+3] for i in range(len(s)-2)} if len(s)>=3 else {s}
def jacc(a,b): return len(a&b)/len(a|b) if (a|b) else 0.0

if __name__=="__main__":
    mentions=[]; gold=[]
    for ent,forms in ENTITIES.items():
        for s in forms: mentions.append(s); gold.append(ent)
    N=len(mentions); allpairs=list(itertools.combinations(range(N),2))
    gold_pairs={(i,j) for i,j in allpairs if gold[i]==gold[j]}
    print(f"mentions={N}  entities={len(ENTITIES)}  all_pairs={len(allpairs)}  true_dup_pairs={len(gold_pairs)}")

    # embeddings (cached)
    cache=json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    for s in mentions:
        if s not in cache: cache[s]=bedrock_embed(s)
    json.dump(cache,open(CACHE,"w"))
    emb=[cache[s] for s in mentions]
    cosm={(i,j):cos(emb[i],emb[j]) for i,j in allpairs}

    def report(name,cand):
        cand=set(cand); tp=cand&gold_pairs
        recall=len(tp)/len(gold_pairs); rr=1-len(cand)/len(allpairs)
        missed=gold_pairs-cand
        miss_ex=[(mentions[i],mentions[j]) for i,j in list(missed)[:6]]
        print(f"  {name:34s} recall {recall:.2f}  RR {rr:.2f}  cand={len(cand):4d}  missed={len(missed)}  {miss_ex if missed else ''}")
        return recall,rr

    print("\n== embedding blocking (cosine >= t) ==")
    for t in (0.85,0.80,0.75,0.70,0.65,0.60):
        report(f"emb cos>={t}", [p for p in allpairs if cosm[p]>=t])

    print("\n== lexical blocking ==")
    tok=[toks(s) for s in mentions]; c3=[char3(s) for s in mentions]
    lex_pairs=[(i,j) for i,j in allpairs if (tok[i]&tok[j]) or jacc(c3[i],c3[j])>=0.4]
    report("shared-token OR char3jacc>=0.4", lex_pairs)

    print("\n== hybrid (embedding cos>=0.70 OR lexical) ==")
    hyb=[p for p in allpairs if cosm[p]>=0.70 or (tok[p[0]]&tok[p[1]]) or jacc(c3[p[0]],c3[p[1]])>=0.4]
    report("hybrid", hyb)

    # ── multi-key blocker: add ID/numeric-normalized keys (recovers ID-format variants) ──
    def aug(s):
        t=set(toks(s)); low=s.lower()
        t|= set(re.findall(r"\d+", low))                       # digit runs: 1001, 55, 7
        t|= {re.sub(r"[^a-z0-9]","",w) for w in re.findall(r"[a-z]+-?\d+|\d+", low)}  # p1001, c55, h7
        return t
    at=[aug(s) for s in mentions]
    print("\n== MULTI-KEY (aug-token OR char3jacc>=0.4 OR emb cos>=0.70) ==")
    mk=[p for p in allpairs if (at[p[0]]&at[p[1]]) or jacc(c3[p[0]],c3[p[1]])>=0.4 or cosm[p]>=0.70]
    r,_=report("multi-key", mk)
    # residual misses = fundamentally context/coreference (first-name-only <-> initial+surname)
    residual=[(mentions[i],mentions[j]) for i,j in (gold_pairs-set(mk))]
    print(f"  residual misses (need context/coreference, not surface): {residual}")
