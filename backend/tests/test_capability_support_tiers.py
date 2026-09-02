"""The add-ons this release does not support, named once."""
import re
from pathlib import Path

from app.capabilities import UNSUPPORTED_BACKENDS

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
