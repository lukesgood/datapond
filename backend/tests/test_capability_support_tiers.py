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
             "streaming", "experiments", "notebooks", "lineage"}
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
    and catalog are not — Athena and Glue are supported adapters."""
    expected = {}
    for capability, backends in CAPABILITY_BACKENDS.items():
        if all(backend in UNSUPPORTED_BACKENDS for backend in backends):
            expected[capability] = "experimental"
    for capability in PREVIEW_CAPABILITIES:
        expected[capability] = "preview"

    assert compute_capabilities({})["support"] == expected
    assert set(expected) == {"pipelines", "streaming", "experiments", "notebooks",
                             "lineage"}
    assert "query" not in expected and "catalog" not in expected


def test_no_core_capability_can_be_marked():
    core = {name for name, value in compute_capabilities({}).items()
            if value is True}
    assert not (core & set(compute_capabilities({})["support"]))


def test_the_vocabulary_is_two_words():
    assert set(compute_capabilities({})["support"].values()) <= {"experimental", "preview"}


# A minimal pipeline, compiled through the real generator, to check the fact this
# release still has: that its DAG comes out declaring placeholder tasks. Same fixture
# shape as tests/test_pipeline_quality_checks.py's _compile/_dag — reused rather than
# invented, because a second compiler harness in this file would just be a second
# thing that can drift from what the compiler actually does.
PIPELINE_SOURCE = '''
from app.pipelines.decorators import pipeline, source, live_table


@pipeline(name="preview_probe", schedule="@daily", owner="t@example.com")
def probe():
    """A pipeline compiled only to inspect its generated DAG."""
    pass


@source(name="orders", connection="conn1", table="public.orders",
        mode="full_refresh", namespace="bronze")
def orders():
    pass


@live_table(name="silver_orders", namespace="silver", engine="trino",
            mode="full_refresh")
def silver_orders():
    return "SELECT * FROM {{ source('orders') }}"
'''


def _compiled_dag(tmp_path) -> str:
    from app.pipelines.compiler import PipelineCompiler
    from app.pipelines.decorators import LiveTableRegistry

    path = tmp_path / "preview_probe.py"
    path.write_text(PIPELINE_SOURCE)
    LiveTableRegistry.reset()
    try:
        result = PipelineCompiler().compile_file(str(path))
        assert result.success, result.validation_errors
        return next(content for kind, content in result.artifacts if "dag" in kind.lower())
    finally:
        LiveTableRegistry.reset()


def test_preview_expires_when_pipelines_stop_compiling_to_placeholders(tmp_path):
    """The tie that makes 'preview' a fact rather than an opinion, not an assertion
    that can be satisfied by a hand-written marker line. Generate a DAG through the
    real compiler and check the fact that actually changes when the declarative
    pipeline runtime lands: whether the generator still emits placeholder tasks."""
    from app.pipelines.dag_generator import refuse_placeholder_deploy, unimplemented_tasks

    dag = _compiled_dag(tmp_path)
    placeholders = unimplemented_tasks(dag)
    assert ("pipelines" in PREVIEW_CAPABILITIES) == bool(placeholders), (
        "the generator no longer emits placeholder tasks, so the declarative "
        "pipeline runtime has landed. Remove 'pipelines' from PREVIEW_CAPABILITIES "
        "— the console is still telling people it cannot deploy."
    )
    if placeholders:
        assert refuse_placeholder_deploy(dag, allow=False), (
            "the generator emits placeholders but the deploy no longer refuses them"
        )
