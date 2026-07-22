import json, subprocess, tempfile, os, re, math
TITAN="amazon.titan-embed-text-v2:0"; REGION="us-east-1"; CACHE="emb_cache.json"
# code-only chunks (the embedder has no semantic signal for the codes) + a confusable sibling each
CHUNKS={
 "99213":"Procedure code 99213 — reimbursement $85 per encounter.",
 "99215":"Procedure code 99215 — reimbursement $170 per encounter.",
 "UB04":"Form UB-04 — submit within 90 days of service.",
 "CMS1500":"Form CMS-1500 — submit within 60 days of service.",
}
QUERIES=[  # plain language; the disambiguator is a code the query never says
 ("How much is reimbursement for a routine short office visit?","99213"),
 ("What is the fee for a long complex consultation?","99215"),
 ("Which claim form for a hospital inpatient bill?","UB04"),
 ("Which claim form does a physician use for an outpatient bill?","CMS1500"),
]
# curated/bootstrapped jargon ontology: plain terms <-> code
ALIASES=[
 {"99213","standard office visit","routine short visit","short office visit"},
 {"99215","complex office visit","long complex consultation"},
 {"ub-04","ub04","hospital inpatient bill","institutional billing","hospital claim form"},
 {"cms-1500","cms1500","physician outpatient bill","professional billing"},
]
def embed(t):
    b={"inputText":t}
    with tempfile.NamedTemporaryFile("w",suffix=".json",delete=False) as f: json.dump(b,f); p=f.name
    o=p+".out"; subprocess.run(["aws","bedrock-runtime","invoke-model","--model-id",TITAN,"--body","fileb://"+p,
      "--cli-binary-format","raw-in-base64-out","--region",REGION,o],check=True,capture_output=True)
    d=json.load(open(o)); os.unlink(p); os.unlink(o); return d["embedding"]
def cos(a,b):
    dt=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b)); return dt/(na*nb) if na and nb else 0
def ql(s): return " "+re.sub(r"[^a-z0-9]"," ",s.lower())+" "
def expand(q):
    add=set()
    for al in ALIASES:
        if any(ql(t).strip() in ql(q) for t in al): add|=al
    add={a for a in add if ql(a).strip() not in ql(q)}
    return q+((" "+" ".join(sorted(add))) if add else "")
cache=json.load(open(CACHE)) if os.path.exists(CACHE) else {}
for t in list(CHUNKS.values())+[q for q,_ in QUERIES]+[expand(q) for q,_ in QUERIES]:
    if t not in cache: cache[t]=embed(t)
json.dump(cache,open(CACHE,"w"))
cids=list(CHUNKS); C=[cache[CHUNKS[c]] for c in cids]
def rank(e): return [cids[i] for i in sorted(range(len(cids)),key=lambda i:-cos(e,C[i]))]
bh=eh=0
print(f"{'query':52s} {'base@1':>7} {'exp@1':>6}")
for q,g in QUERIES:
    rb=rank(cache[q]); re_=rank(cache[expand(q)])
    b=int(rb[0]==g); e=int(re_[0]==g); bh+=b; eh+=e
    print(f"{q[:52]:52s} {('HIT' if b else rb[0]):>7} {('HIT' if e else re_[0]):>6}")
n=len(QUERIES)
print(f"\nrecall@1  baseline {bh/n:.2f}   expanded {eh/n:.2f}   delta {(eh-bh)/n:+.2f}")
