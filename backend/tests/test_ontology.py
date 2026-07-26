"""Phase 0 ontology slice — expansion core + capability gating."""
from app.api.ontology import expand_query_text
from app.capabilities import compute_capabilities

CONCEPTS = [
    {"name": "Deductible", "pii": False, "terms": ["excess", "self-insured retention"]},
    {"name": "UB-04", "pii": False, "terms": ["ub04", "hospital inpatient bill", "institutional claim form"]},
    {"name": "Policyholder", "pii": True, "terms": ["insured", "policy holder"]},
]


def test_expansion_adds_aliases_on_term_hit():
    q, matched = expand_query_text("what is the excess for a claim", CONCEPTS)
    assert [m["name"] for m in matched] == ["Deductible"]
    # the query gains the concept name + sibling terms, minus what it already contains
    assert "Deductible" in q and "self-insured retention" in q
    assert "excess" not in matched[0]["added"]  # already present in the query


def test_expansion_matches_concept_name_and_code_terms():
    q, matched = expand_query_text("which form is the UB-04 for", CONCEPTS)
    assert [m["name"] for m in matched] == ["UB-04"]
    assert "hospital inpatient bill" in q


def test_no_match_is_a_noop():
    q, matched = expand_query_text("completely unrelated question", CONCEPTS)
    assert q == "completely unrelated question"
    assert matched == []


def test_word_boundary_no_substring_false_hits():
    # "insuredness" must not fire the "insured" term.
    q, matched = expand_query_text("insuredness is not a word", CONCEPTS)
    assert matched == []
    assert q == "insuredness is not a word"


def test_pii_flag_surfaces_on_match():
    _, matched = expand_query_text("can the insured cancel", CONCEPTS)
    assert matched and matched[0]["name"] == "Policyholder"
    assert matched[0]["pii"] is True


def test_korean_query_matching():
    concepts = [{"name": "환불", "pii": False, "terms": ["전액 환불", "refund"]}]
    q, matched = expand_query_text("환불 처리 기간은?", concepts)
    assert matched and matched[0]["name"] == "환불"
    assert "refund" in q


def test_capability_fail_closed_and_opt_in():
    assert compute_capabilities({})["ontology"] is False
    assert compute_capabilities({"FEATURE_ONTOLOGY": "true"})["ontology"] is True
