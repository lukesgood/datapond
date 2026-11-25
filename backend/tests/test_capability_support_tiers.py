"""The add-ons this release does not support, named once."""
import re
from pathlib import Path

from app.capabilities import (CAPABILITY_BACKENDS, PREVIEW_CAPABILITIES,
                              UNSUPPORTED_BACKENDS, compute_capabilities)

SUPPORT_MD = Path(__file__).resolve().parents[2] / "SUPPORT.md"


def _anchored_addons() -> set:
    """The names between SUPPORT.md's markers, upper-cased to match FEATURE_* flags."""
    body = SUPPORT_MD.read_text()
    block = re.search(r"<!-- unsupported-addons -->(.*?)<!-- /unsupported-addons -->",
                      body, re.S)
    assert block, "SUPPORT.md lost its unsupported-addons anchor"
    return {line.strip("- ").strip().upper()
            for line in block.group(1).splitlines() if line.strip().startswith("-")}


def test_the_code_and_the_document_name_the_same_add_ons():
    """One list, two readers. A name added to the document without a tier — or a tier
    for a name the document no longer disclaims — is a product claim drifting from what
    the console shows."""
    assert set(UNSUPPORTED_BACKENDS) == _anchored_addons()


def test_every_component_gated_capability_declares_its_backends():
    """A capability with no entry can never earn a tier, and would be silently
    supported forever."""
    gated = {"connectors", "catalog", "query", "dashboards", "pipelines",
             "experiments", "notebooks"}
    assert set(CAPABILITY_BACKENDS) == gated


def test_the_table_answers_the_same_as_the_flags():
    """The extraction is behaviour-preserving: with a backend on, its capability is on;
    with every backend off, it is off."""
    for capability, backends in CAPABILITY_BACKENDS.items():
        for backend in backends:
            assert compute_capabilities({f"FEATURE_{backend}": "true"})[capability] is True
        assert compute_capabilities({})[capability] is False


def test_the_support_map_is_the_derivation_not_a_hand_written_list():
    """Computed here independently: a capability is experimental exactly when every
    backend that can enable it is one the product does not support. That is why query
    and catalog are not — Trino (the engine, 2.4) and Glue are supported adapters."""
    expected = {}
    for capability, backends in CAPABILITY_BACKENDS.items():
        if all(backend in UNSUPPORTED_BACKENDS for backend in backends):
            expected[capability] = "experimental"
    for capability in PREVIEW_CAPABILITIES:
        expected[capability] = "preview"

    assert compute_capabilities({})["support"] == expected
    assert set(expected) == {"pipelines", "experiments", "notebooks"}
    assert "query" not in expected and "catalog" not in expected


def test_openmetadata_is_a_service_not_a_capability():
    """The add-on the console has no page for.

    OpenMetadata is disclaimed in SUPPORT.md like the others, but unlike them it
    backs no capability: it ships its own UI, and connector sync writes lineage edges
    there rather than into a DataPond screen. `lineage` used to appear in the payload
    anyway, gating nothing a person could open and carrying a support tier nothing
    rendered. Re-adding it means adding the screen too — not the key on its own."""
    assert "OPENMETADATA" in UNSUPPORTED_BACKENDS, "still an add-on we do not support"
    backing = {b for backends in CAPABILITY_BACKENDS.values() for b in backends}
    assert "OPENMETADATA" not in backing

    caps = compute_capabilities({"FEATURE_OPENMETADATA": "true"})
    assert "lineage" not in caps, "a capability no screen consumes is back in the payload"
    assert "lineage" not in caps["support"]


def test_no_core_capability_can_be_marked():
    core = {name for name, value in compute_capabilities({}).items()
            if value is True}
    assert not (core & set(compute_capabilities({})["support"]))


def test_the_vocabulary_is_two_words():
    assert set(compute_capabilities({})["support"].values()) <= {"experimental", "preview"}


def test_no_capability_is_in_preview_since_the_pipeline_builder_was_removed():
    """`preview` meant "cannot complete its headline feature". The declarative pipeline
    builder was the only one (placeholder DAGs, deploy refused) and is gone in 2.7."""
    assert PREVIEW_CAPABILITIES == ()
    assert compute_capabilities({"FEATURE_AIRFLOW": "true"})["support"]["pipelines"] == "experimental"


def test_connectors_need_only_trino():
    """2.5: every database source is a Trino catalog and the sync is a Trino statement,
    so ingestion exists exactly when the engine does. A Polaris or Glue catalog alone
    gives a place to write and nothing that can write there."""
    assert CAPABILITY_BACKENDS["connectors"] == ("TRINO",)
