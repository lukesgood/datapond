#!/usr/bin/env python3
"""
A-Box experiment — entity extraction + resolution (the Phase-1 hard risk).
The deal-killer in regulated buyers = a FALSE MERGE (two different real entities collapsed
into one). This measures extraction quality AND resolution quality, with hard negatives
(similar names that are DIFFERENT entities), comparing:
   baseline : normalized-string clustering
   llm      : context-aware LLM clustering (the "product" approach)
Model: Claude Haiku (extract) + Sonnet (resolve) on Bedrock.
"""
import json, subprocess, tempfile, os, re, itertools

HAIKU  = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
SONNET = "us.anthropic.claude-sonnet-4-6"
REGION = "us-east-1"

CORPUS = {
 "d1_contract.md": "Acme Corporation signed a new agreement. Acme Corp will be billed monthly. "
                   "The client Acme is managed by account manager John A. Smith.",
 "d2_billing.md":  "Invoice sent to Acme for policy P-1001. J. Smith approved the P-1001 policy terms. "
                   "Note: Acme Holdings, the parent company, is tracked as a separate account.",
 "d3_support.md":  "Jane Smith from Globex Inc. opened a support ticket. John reviewed it that afternoon. "
                   "Globex is a new customer this quarter.",
 "d4_memo.md":     "Acme Holdings requested a compliance report. Unlike Acme Corporation, Holdings holds "
                   "no active policy. John Smith will follow up with the client.",
}

# GOLD: canonical entity -> accepted normalized surface forms (mention keys)
def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
GOLD = {
 "AcmeCorporation": {"acme corporation", "acme corp", "acme", "client acme"},
 "AcmeHoldings":    {"acme holdings", "holdings"},
 "JohnASmith":      {"john a. smith", "john smith", "j. smith", "john"},
 "JaneSmith":       {"jane smith"},
 "PolicyP1001":     {"policy p-1001", "p-1001 policy", "p-1001", "policy p1001"},
 "GlobexInc":       {"globex inc", "globex inc.", "globex"},
}
GOLD_NORM = {ent: {norm(f) for f in forms} for ent, forms in GOLD.items()}
def gold_of(surface):
    n = norm(surface)
    for ent, forms in GOLD_NORM.items():
        if n in forms: return ent
    return None

def bedrock(prompt, model, max_tokens=1500):
    body = {"anthropic_version":"bedrock-2023-05-31","max_tokens":max_tokens,
            "messages":[{"role":"user","content":prompt}]}
    with tempfile.NamedTemporaryFile("w",suffix=".json",delete=False) as f:
        json.dump(body,f); bp=f.name
    out=bp+".out"
    subprocess.run(["aws","bedrock-runtime","invoke-model","--model-id",model,"--body","fileb://"+bp,
                    "--cli-binary-format","raw-in-base64-out","--region",REGION,out],
                   check=True,capture_output=True)
    d=json.load(open(out)); os.unlink(bp); os.unlink(out); return d["content"][0]["text"]
def pj(t):
    t=re.sub(r"^```(?:json)?|```$","",t.strip(),flags=re.M).strip()
    m=re.search(r"[\{\[].*[\}\]]",t,re.S); return json.loads(m.group(0) if m else t)

EXTRACT="""Extract entity MENTIONS from the document. Return STRICT JSON list only:
[{{"surface": exact surface text of the mention, "type": Person|Organization|Policy}}]
Include every mention of a named organization, person, or policy id (including short/abbreviated
and coreferential forms like "the client Acme" or a bare first name if it names a person).
DOCUMENT ({name}): {doc}
JSON:"""

RESOLVE="""You are doing entity RESOLUTION. Below are entity mentions extracted from several documents,
each with the sentence it appeared in. Cluster the mentions that refer to the SAME real-world entity.
CRITICAL: similar names can be DIFFERENT entities — e.g. "Acme Corporation" and "Acme Holdings" are a
company and its separate parent; two people sharing a surname are different. Use the sentence context.
Do NOT merge different entities. Return STRICT JSON list of clusters only:
[{{"canonical": a clear canonical name, "mentions": [exact surface strings in this cluster]}}]
MENTIONS (JSON): {mentions}
Clusters JSON:"""

def extract():
    mentions=[]  # {surface, type, doc, ctx}
    for name,doc in CORPUS.items():
        for m in pj(bedrock(EXTRACT.format(name=name,doc=doc),HAIKU)):
            s=m.get("surface","").strip()
            if not s: continue
            ctx=next((sent.strip() for sent in re.split(r'(?<=[.])\s+',doc) if s in sent), doc)
            mentions.append({"surface":s,"type":m.get("type"),"doc":name,"ctx":ctx})
    return mentions

def clusters_to_pairs(clusters):
    """clusters: list of sets of mention-indices -> set of same-entity index pairs."""
    pairs=set()
    for c in clusters:
        for a,b in itertools.combinations(sorted(c),2): pairs.add((a,b))
    return pairs

def evaluate(name, mentions, pred_clusters):
    # keep only mentions that map to a gold entity (evaluable set)
    idx=[i for i,m in enumerate(mentions) if gold_of(m["surface"])]
    gold_lbl={i:gold_of(mentions[i]["surface"]) for i in idx}
    # gold clusters over evaluable indices
    gold_clusters={}
    for i in idx: gold_clusters.setdefault(gold_lbl[i],set()).add(i)
    gold_pairs=clusters_to_pairs(gold_clusters.values())
    # restrict predicted clusters to evaluable indices
    pred_eval=[{i for i in c if i in idx} for c in pred_clusters]
    pred_pairs=clusters_to_pairs([c for c in pred_eval if len(c)>1])
    tp=pred_pairs & gold_pairs
    prec=len(tp)/len(pred_pairs) if pred_pairs else 1.0
    rec=len(tp)/len(gold_pairs) if gold_pairs else 1.0
    f1=2*prec*rec/(prec+rec) if (prec+rec) else 0
    false_merges=[(mentions[a]["surface"],mentions[b]["surface"]) for a,b in (pred_pairs-gold_pairs)]
    false_splits=len(gold_pairs-pred_pairs)
    print(f"\n--- {name} resolution ---")
    print(f"  pairwise  precision {prec:.2f}  recall {rec:.2f}  F1 {f1:.2f}")
    print(f"  FALSE MERGES (dangerous): {len(false_merges)}  {false_merges if false_merges else ''}")
    print(f"  false splits: {false_splits}")
    return dict(prec=prec,rec=rec,f1=f1,fm=len(false_merges),fs=false_splits)

def surfaces_to_indices(mentions, surfaces):
    """map a cluster's surface strings back to mention indices (by normalized surface)."""
    out=set()
    want={norm(s) for s in surfaces}
    for i,m in enumerate(mentions):
        if norm(m["surface"]) in want: out.add(i)
    return out

if __name__=="__main__":
    print("== A-Box: entity extraction (Haiku) ==")
    mentions=extract()
    ev=[i for i,m in enumerate(mentions) if gold_of(m["surface"])]
    print(f"  {len(mentions)} mentions extracted; {len(ev)} map to a gold entity")
    # extraction recall: gold entities that got at least one mention
    got={gold_of(mentions[i]['surface']) for i in ev}
    print(f"  extraction: {len(got)}/{len(GOLD)} gold entities have >=1 mention")

    # baseline resolver: cluster by normalized surface (strip corp/inc/co suffixes)
    def base_norm(s):
        n=norm(s)
        for suf in ("corporation","corp","incorporated","inc","company","co","ltd"):
            if n.endswith(suf) and len(n)>len(suf)+1: n=n[:-len(suf)]
        return n
    bmap={}
    for i,m in enumerate(mentions): bmap.setdefault(base_norm(m["surface"]),set()).add(i)
    baseline=list(bmap.values())
    evaluate("BASELINE (normalized string)", mentions, baseline)

    # llm resolver
    print("\n== resolution (Sonnet, context-aware) ==")
    mlist=[{"surface":m["surface"],"ctx":m["ctx"]} for m in mentions]
    clusters=pj(bedrock(RESOLVE.format(mentions=json.dumps(mlist,ensure_ascii=False)),SONNET,max_tokens=2000))
    llm=[surfaces_to_indices(mentions,c.get("mentions",[])) for c in clusters]
    print("  LLM clusters:")
    for c in clusters: print(f"    {c.get('canonical')}: {c.get('mentions')}")
    evaluate("LLM (context-aware)", mentions, llm)
