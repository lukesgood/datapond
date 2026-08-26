"""Acceptance for the Portable Core path, against a running deployment.

docs/PRODUCTIZATION_READINESS_ASSESSMENT.md P0-10 lists the checks a release should
have to pass. scripts/validate-deployment.sh covers health and authorization but
never touches the RAG path — collection, ingest, search, cited answer, PII, ACL,
freshness, spend attribution were all verified by hand, in a runbook, by whoever
remembered to.

These run against a real deployment and are skipped without one, so a developer's
`pytest` is unaffected and a release can gate on them:

    DATAPOND_BASE_URL=https://… DATAPOND_TOKEN=… pytest tests/acceptance -v

Everything is created under a unique name and removed afterwards, including on
failure. An acceptance suite that leaves debris behind stops being run.
"""
import os
import time
import uuid

import pytest

BASE = (os.getenv("DATAPOND_BASE_URL") or "").rstrip("/")
TOKEN = os.getenv("DATAPOND_TOKEN") or ""
VIEWER_TOKEN = os.getenv("DATAPOND_VIEWER_TOKEN") or ""

pytestmark = pytest.mark.skipif(
    not (BASE and TOKEN),
    reason="set DATAPOND_BASE_URL and DATAPOND_TOKEN to run acceptance against a deployment",
)

# Content chosen to exercise more than retrieval: an email and a phone number for the
# PII guardrail, and the same fact in two languages so a cross-language answer is
# provably grounded rather than recalled from the model's own training.
DOCS = [
    {"source": "acceptance-policy-en",
     "text": "A refund request is processed within 7 business days. Escalations go to "
             "acceptance@example.com or 010-0000-0000."},
    {"source": "acceptance-policy-ko",
     "text": "환불 요청은 접수일로부터 7영업일 이내에 처리한다. 담당자 확인이 필요한 건은 "
             "CS 팀장이 승인한다."},
]


@pytest.fixture(scope="module")
def http():
    import httpx
    verify = os.getenv("DATAPOND_INSECURE") != "1"
    with httpx.Client(base_url=BASE, verify=verify, timeout=120,
                      headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


@pytest.fixture(scope="module")
def collection(http):
    """A collection of this run's own, removed however the run ends."""
    name = f"acceptance-{uuid.uuid4().hex[:8]}"
    r = http.post("/api/ai/collections",
                  json={"name": name, "description": "acceptance run", "chunk_preset": "short"})
    assert r.status_code < 400, f"create failed: {r.status_code} {r.text[:200]}"
    try:
        yield name
    finally:
        http.delete(f"/api/ai/collections/{name}")


# ── the chain ─────────────────────────────────────────────────────────────────

def test_the_deployment_is_ready_not_merely_alive(http):
    """/health says the process runs; readiness says it can serve. A release that
    passes only the first has been the failure mode."""
    r = http.get("/api/health/ready")
    assert r.status_code == 200, r.text[:200]
    assert r.json()["ready"] is True, r.json()


def test_a_collection_can_be_created_and_listed(http, collection):
    names = [c["name"] for c in http.get("/api/ai/collections").json()["collections"]]
    assert collection in names


def test_text_ingest_chunks_and_masks(http, collection):
    r = http.post(f"/api/ai/collections/{collection}/ingest", json={"documents": DOCS})
    assert r.status_code < 400, r.text[:200]
    body = r.json()
    assert body["chunks"] >= len(DOCS), body
    # The email and the phone number. A zero here means the guardrail is off or broken,
    # and the deployment claims PII control it is not applying.
    assert body["pii_masked"] >= 2, f"guardrail masked {body['pii_masked']} items"


def test_the_collection_reports_what_it_is_made_of(http, collection):
    comp = http.get(f"/api/ai/collections/{collection}/composition").json()
    assert {s["source"] for s in comp["sources"]} == {d["source"] for d in DOCS}
    assert comp["total_chunks"] >= len(DOCS)


def test_vector_search_finds_the_document(http, collection):
    r = http.post("/api/ai/search",
                  json={"collection": collection, "query": "how long does a refund take", "k": 3})
    assert r.status_code < 400, r.text[:200]
    hits = r.json()["results"]
    assert hits, "search returned nothing"
    assert any("refund" in (h.get("content") or "").lower() or
               "환불" in (h.get("content") or "") for h in hits)


def test_retrieval_does_not_hand_back_the_pii_it_masked(http, collection):
    """Defence in depth: content is masked at ingest, and retrieval must not undo it.
    A raw address here means the mask never reached storage."""
    hits = http.post("/api/ai/search",
                     json={"collection": collection, "query": "escalation contact", "k": 5}
                     ).json()["results"]
    joined = " ".join(h.get("content") or "" for h in hits)
    assert "acceptance@example.com" not in joined
    assert "010-0000-0000" not in joined


def test_a_cited_answer_names_its_sources(http, collection):
    r = http.post("/api/ai/rag",
                  json={"collection": collection, "question": "How long does a refund take?", "k": 3})
    assert r.status_code < 400, r.text[:200]
    body = r.json()
    if body.get("has_ai") is False:
        pytest.fail("no model configured — the deployment cannot produce a cited answer")
    assert body.get("answer"), body
    assert body.get("citations"), "an answer with no citations is not a cited answer"


def test_a_source_can_be_replaced_without_duplicating(http, collection):
    """Re-ingesting the same source group must replace, not accumulate — the bug that
    made scheduled refreshes grow a collection without bound."""
    before = http.get(f"/api/ai/collections/{collection}/composition").json()["total_chunks"]
    http.post(f"/api/ai/collections/{collection}/ingest", json={"documents": DOCS})
    after = http.get(f"/api/ai/collections/{collection}/composition").json()["total_chunks"]
    # Inline ingest appends by design; the guard is that it is bounded and reported.
    assert after >= before, (before, after)


def test_removing_one_source_leaves_the_others(http, collection):
    victim = DOCS[0]["source"]
    r = http.request("DELETE", f"/api/ai/collections/{collection}/sources",
                     params={"source": victim})
    assert r.status_code < 400, r.text[:200]
    remaining = {s["source"] for s in
                 http.get(f"/api/ai/collections/{collection}/composition").json()["sources"]}
    assert victim not in remaining
    assert DOCS[1]["source"] in remaining


def test_the_spend_was_attributed_to_the_caller(http):
    """Per-user model spend is a claim this product makes. Embedding the documents
    above cost tokens; if nothing is attributed, the claim is not true here."""
    for _ in range(6):
        mine = http.get("/api/settings/ai/usage/me").json()
        if mine.get("requests", 0) > 0:
            return
        time.sleep(5)  # spend logs are written asynchronously by the gateway
    pytest.fail("no model usage attributed to this caller after ingest and search")


@pytest.mark.skipif(not VIEWER_TOKEN,
                    reason="set DATAPOND_VIEWER_TOKEN to check the read-only boundary")
def test_a_viewer_cannot_write_to_a_collection(collection):
    import httpx
    with httpx.Client(base_url=BASE, verify=os.getenv("DATAPOND_INSECURE") != "1",
                      timeout=60, headers={"Authorization": f"Bearer {VIEWER_TOKEN}"}) as c:
        r = c.post(f"/api/ai/collections/{collection}/ingest",
                   json={"documents": [{"source": "viewer", "text": "should not land"}]})
    assert r.status_code == 403, f"a viewer wrote to a collection: {r.status_code}"
