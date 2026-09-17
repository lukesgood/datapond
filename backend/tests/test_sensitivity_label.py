"""One label, both consequences — and it can only ever tighten.

Before this, a collection marked `block` for PII still had its text embedded by a cloud
provider: masking was a property of the collection and egress a property of the
deployment, and nothing tied them together.
"""
import pytest

from app import sensitivity
from app.api import ai_backends
from app.guardrails import pii_ko


def test_unknown_and_missing_labels_derive_nothing():
    for label in (None, "", "secret", "CONFIDENTIAL!", 7):
        assert sensitivity.normalize(label) is None
        assert sensitivity.pii_floor(label) is None
        assert sensitivity.forces_local_only(label) is False


def test_labels_are_case_and_space_tolerant():
    assert sensitivity.normalize("  Restricted ") == "restricted"


def test_the_masking_floor_each_label_implies():
    assert sensitivity.pii_floor("public") is None
    assert sensitivity.pii_floor("internal") is None
    assert sensitivity.pii_floor("confidential") == "mask"
    assert sensitivity.pii_floor("restricted") == "block"


def test_only_restricted_forbids_egress():
    assert sensitivity.forces_local_only("restricted") is True
    for label in ("public", "internal", "confidential"):
        assert sensitivity.forces_local_only(label) is False


def test_a_label_tightens_masking(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "off")
    with pii_ko.scope(sensitivity.pii_floor("confidential")):
        assert pii_ko.get_mode() == "mask"


def test_a_label_cannot_loosen_masking(monkeypatch):
    """`public` says nothing, and saying nothing must not weaken the deployment."""
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "block")
    with pii_ko.scope(sensitivity.pii_floor("public")):
        assert pii_ko.get_mode() == "block"


def test_egress_scope_defaults_to_the_deployment(monkeypatch):
    monkeypatch.delenv("AI_EGRESS_POLICY", raising=False)
    assert ai_backends.egress_policy() == "cloud-allowed"


def test_a_restricted_collection_forces_local_only(monkeypatch):
    """The deployment allows the cloud; this request must not use it."""
    monkeypatch.delenv("AI_EGRESS_POLICY", raising=False)

    import contextvars

    def _in_request():
        ai_backends.require_local_only()
        return ai_backends.egress_policy()

    # a copied context is what a request gets, so the scope must not leak out of it
    assert contextvars.copy_context().run(_in_request) == "local-only"
    assert ai_backends.egress_policy() == "cloud-allowed", "scope leaked past the request"


def test_the_scope_cannot_permit_what_the_deployment_forbids(monkeypatch):
    monkeypatch.setenv("AI_EGRESS_POLICY", "local-only")
    assert ai_backends.egress_policy() == "local-only"
    assert ai_backends.env_egress_policy() == "local-only"
