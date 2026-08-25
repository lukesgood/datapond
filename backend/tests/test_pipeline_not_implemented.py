"""A pipeline that does nothing must not report success.

The declarative pipeline compiler emits a DAG whose ingest, quality, transform and
checkpoint tasks are all EmptyOperator with a TODO beside them. The API wrote that
DAG to Airflow, unpaused it, marked the pipeline "deployed" and returned 200. Every
run then went green having moved no data and checked no quality rule — the failure
mode where the operator's own dashboard tells them it worked.

Two things follow, and the tests below cover both: the generated DAG must say what
is missing, and deploy must refuse to pretend.
"""
import pytest

from app.pipelines.dag_generator import UNIMPLEMENTED_MARKER, unimplemented_tasks


def test_a_dag_with_no_marker_has_nothing_unimplemented():
    assert unimplemented_tasks("from airflow import DAG\n") == []


def test_the_marker_lists_the_tasks_that_do_nothing():
    code = f'{UNIMPLEMENTED_MARKER} = ["ingest__orders", "transform__silver"]\n'
    assert unimplemented_tasks(code) == ["ingest__orders", "transform__silver"]


def test_an_empty_marker_means_the_dag_is_real():
    assert unimplemented_tasks(f"{UNIMPLEMENTED_MARKER} = []\n") == []


def test_a_malformed_marker_is_treated_as_unimplemented():
    """Failing closed. A marker we cannot read is not evidence that the tasks work,
    and the whole point of this check is to stop guessing in that direction."""
    assert unimplemented_tasks(f"{UNIMPLEMENTED_MARKER} = <broken>\n") == ["<unparseable>"]


# ── the generated DAG ─────────────────────────────────────────────────────────
#
# Compiled through the real compiler, from a pipeline written the way a user writes
# one. The repository has no example pipeline, so the existing compiler tests skip
# and this path had no coverage at all — a fixture that skips is not a test.

PIPELINE_SOURCE = '''
from app.pipelines.decorators import pipeline, source, live_table, quality


@pipeline(name="coverage_demo", schedule="@daily", owner="t@example.com")
def demo():
    """A pipeline for exercising the generator."""
    pass


@source(name="orders", connection="conn1", table="public.orders",
        mode="incremental", watermark_column="updated_at", namespace="bronze")
def orders():
    pass


@live_table(name="silver_orders", namespace="silver", engine="trino",
            mode="incremental", watermark_column="updated_at")
@quality.expect_or_fail("id_present", "id IS NOT NULL")
def silver_orders():
    return "SELECT * FROM {{ source('orders') }}"
'''


@pytest.fixture
def example_dag(tmp_path):
    from app.pipelines.compiler import PipelineCompiler
    from app.pipelines.decorators import LiveTableRegistry

    source_file = tmp_path / "demo_pipeline.py"
    source_file.write_text(PIPELINE_SOURCE)
    LiveTableRegistry.reset()
    try:
        result = PipelineCompiler().compile_file(str(source_file))
        assert result.success, result.validation_errors
        return next(c for t, c in result.artifacts if t == "airflow_dag")
    finally:
        LiveTableRegistry.reset()


def test_the_generated_dag_declares_which_tasks_are_not_implemented(example_dag):
    assert UNIMPLEMENTED_MARKER in example_dag
    assert unimplemented_tasks(example_dag), "the placeholder DAG claims to be complete"


def test_an_unimplemented_task_fails_instead_of_succeeding(example_dag):
    """EmptyOperator succeeds. A task standing in for work nobody wrote must go red,
    or Airflow's own status page becomes the thing telling the operator it worked."""
    assert "EmptyOperator(" not in example_dag
    assert "NotImplementedError" in example_dag


def test_the_generated_dag_is_valid_python(example_dag):
    import ast
    ast.parse(example_dag)


def test_the_marker_names_every_placeholder_task(example_dag):
    """Ingest, quality, transform and checkpoint are all placeholders today; the
    marker must not under-report and let deploy think part of it is real."""
    named = unimplemented_tasks(example_dag)
    assert any(t.startswith("ingest__") for t in named)
    assert any(t.startswith("transform__") for t in named)


# ── the deploy gate ───────────────────────────────────────────────────────────

from app.pipelines.dag_generator import refuse_placeholder_deploy


def test_a_real_dag_deploys():
    assert refuse_placeholder_deploy("from airflow import DAG\n", allow=False) is None


def test_a_placeholder_dag_is_refused():
    code = f'{UNIMPLEMENTED_MARKER} = ["ingest__orders"]\n'
    detail = refuse_placeholder_deploy(code, allow=False)
    assert detail and "ingest__orders" in detail


def test_the_refusal_says_how_to_override_it():
    code = f'{UNIMPLEMENTED_MARKER} = ["ingest__orders"]\n'
    assert "PIPELINES_ALLOW_PLACEHOLDER_DEPLOY" in refuse_placeholder_deploy(code, allow=False)


def test_an_explicit_override_is_honoured():
    """Someone testing the scheduling shape has a real reason to deploy a skeleton.
    The point is that they have to say so, not that it is impossible."""
    code = f'{UNIMPLEMENTED_MARKER} = ["ingest__orders"]\n'
    assert refuse_placeholder_deploy(code, allow=True) is None
