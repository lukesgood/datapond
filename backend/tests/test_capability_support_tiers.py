"""The add-ons this release does not support, named once."""
import re
from pathlib import Path

from app.capabilities import CAPABILITY_BACKENDS, UNSUPPORTED_BACKENDS, compute_capabilities

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
             "streaming", "experiments", "notebooks", "lineage"}
    assert set(CAPABILITY_BACKENDS) == gated


def test_the_table_answers_the_same_as_the_flags():
    """The extraction is behaviour-preserving: with a backend on, its capability is on;
    with every backend off, it is off."""
    for capability, backends in CAPABILITY_BACKENDS.items():
        for backend in backends:
            assert compute_capabilities({f"FEATURE_{backend}": "true"})[capability] is True
        assert compute_capabilities({})[capability] is False
