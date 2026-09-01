"""Validating a pipeline must not run it.

`/pipelines/validate` and `/pipelines/compile` take Python source in the request body.
The compiler used to load that source with `importlib` and call `exec_module` on it, so
every top-level statement in a submitted file ran inside the backend process — with the
pod's filesystem, its network and its credentials. A security audit reproduced it with
a marker file; that reproduction is the first two tests below, at the compiler and at
the route.

The pipeline DSL is declarative: decorators with literal arguments, and function bodies
that return a SQL string. Nothing in it has to run to be described, so the compiler now
reads the definition with `ast` (`app/pipelines/ast_reader.py`). The rest of this file
is the other half of the bargain — that the endpoints still report what they promise:
the pipeline's name, its dependency graph, its execution batches and its warnings.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import auth
from app.api import pipelines as pipelines_api
from app.pipelines.compiler import PipelineCompiler
from app.pipelines.decorators import LiveTableRegistry
from app.pipelines.dependency_graph import DependencyGraphBuilder

# Captured before anything reassigns it: `dependency_overrides` must key on the same
# function object FastAPI bound into the route's dependency graph at import time.
_REAL_REQUIRE_USER = auth.require_user


@pytest.fixture(autouse=True)
def reset_registry():
    LiveTableRegistry.reset()
    yield
    LiveTableRegistry.reset()


def _hostile_source(marker) -> str:
    """A pipeline file whose top level does something no validator should do."""
    return f'''
from pathlib import Path

Path({str(marker)!r}).write_text("the compiler executed submitted code")

from app.pipelines.decorators import pipeline, source, live_table


@pipeline(name="looks_harmless", schedule="@daily")
def looks_harmless():
    """Nothing to see here."""
    pass


@source(name="orders", connection="conn1", table="public.orders")
def orders():
    pass


@live_table(name="silver_orders", namespace="silver")
def silver_orders():
    return "SELECT * FROM {{{{ source('orders') }}}}"
'''


# ── the audit's reproduction ──────────────────────────────────────────────────

def test_compiling_a_module_does_not_run_its_top_level(tmp_path):
    marker = tmp_path / "pwned.txt"
    pipeline_file = tmp_path / "hostile.py"
    pipeline_file.write_text(_hostile_source(marker))

    PipelineCompiler().compile_file(str(pipeline_file))

    assert not marker.exists(), (
        "the compiler executed the submitted module's top-level code")


def test_validating_a_module_does_not_run_its_top_level(tmp_path):
    marker = tmp_path / "pwned.txt"
    pipeline_file = tmp_path / "hostile.py"
    pipeline_file.write_text(_hostile_source(marker))

    PipelineCompiler().validate_only(str(pipeline_file))

    assert not marker.exists(), (
        "the validator executed the submitted module's top-level code")


def _client() -> TestClient:
    """The pipelines router with a `data_engineer` signed in.

    `pipeline:write` is exactly the gate these two routes carry today, so this is the
    caller the audit was about: a role for connecting data sources, not for running
    code as the backend.
    """
    app = FastAPI()
    app.include_router(pipelines_api.router, prefix="/api")

    async def _signed_in():
        return {"id": "u-de", "username": "dana", "role": "data_engineer",
                "permissions": ["pipeline:write"]}

    app.dependency_overrides[_REAL_REQUIRE_USER] = _signed_in
    return TestClient(app)


def test_the_validate_endpoint_does_not_run_the_code_it_is_sent(tmp_path):
    """The finding as it was reported: submitted source, over HTTP, no marker."""
    marker = tmp_path / "pwned.txt"

    response = _client().post("/api/pipelines/validate",
                              json={"code": _hostile_source(marker)})

    assert response.status_code == 200, response.text
    assert not marker.exists(), "POST /pipelines/validate executed the request body"
    assert response.json()["pipeline_name"] == "looks_harmless"


def test_the_compile_endpoint_does_not_run_the_code_it_is_sent(tmp_path):
    marker = tmp_path / "pwned.txt"

    response = _client().post("/api/pipelines/compile",
                              json={"code": _hostile_source(marker)})

    assert response.status_code == 200, response.text
    assert not marker.exists(), "POST /pipelines/compile executed the request body"
    assert response.json()["pipeline_name"] == "looks_harmless"


def test_an_import_the_backend_does_not_have_is_not_an_error(tmp_path):
    """Nothing in the file is imported any more, including its own imports — so a
    pipeline written against a library the backend has never installed still
    describes itself, and importing one for its side effects buys nothing."""
    pipeline_file = tmp_path / "exotic.py"
    pipeline_file.write_text('''
import a_library_this_backend_does_not_have
from app.pipelines.decorators import pipeline, source, live_table

@pipeline(name="exotic", schedule="@daily")
def exotic(): pass

@source(name="raw", connection="conn1", table="public.raw")
def raw(): pass

@live_table(name="clean")
def clean():
    return "SELECT * FROM {{ source('raw') }}"
''')

    result = PipelineCompiler().validate_only(str(pipeline_file))

    assert result.success, result.validation_errors


# ── what validation still reports ─────────────────────────────────────────────

MEDALLION = '''
from app.pipelines.decorators import pipeline, source, live_table, quality


@pipeline(name="medallion", schedule="@hourly", owner="dana@example.com",
          tags=["sales"], max_retries=3)
def medallion():
    """Bronze to gold."""
    pass


@source(name="orders", connection="oltp", table="public.orders",
        mode="incremental", watermark_column="updated_at")
def orders():
    pass


@live_table(name="clean_orders", namespace="silver", mode="incremental",
            watermark_column="updated_at", partition_by=["order_date"])
@quality.expect_or_fail("id_present", "order_id IS NOT NULL")
@quality.expect("amount_positive", "amount > 0")
def clean_orders():
    return "SELECT * FROM {{ source('orders') }} WHERE {{ incremental_filter('updated_at') }}"


@live_table(name="daily_sales", namespace="gold")
def daily_sales():
    return "SELECT order_date, sum(amount) FROM {{ ref('clean_orders') }} GROUP BY 1"
'''


@pytest.fixture
def medallion_file(tmp_path):
    path = tmp_path / "medallion.py"
    path.write_text(MEDALLION)
    return str(path)


def test_the_declared_pipeline_is_reported_in_full(medallion_file):
    pipeline, notes = PipelineCompiler()._read_pipeline_definition(medallion_file)

    assert pipeline.pipeline.name == "medallion"
    assert pipeline.pipeline.schedule == "@hourly"
    assert pipeline.pipeline.owner == "dana@example.com"
    assert pipeline.pipeline.tags == ["sales"]
    assert pipeline.pipeline.max_retries == 3
    assert pipeline.pipeline.description == "Bronze to gold."
    assert set(pipeline.sources) == {"orders"}
    assert pipeline.sources["orders"].connection_id == "oltp"
    assert pipeline.sources["orders"].watermark_column == "updated_at"
    assert set(pipeline.tables) == {"clean_orders", "daily_sales"}
    assert pipeline.tables["clean_orders"].partition_by == ["order_date"]
    assert notes == []


def test_quality_checks_declared_on_a_table_are_reported(medallion_file):
    pipeline, _ = PipelineCompiler()._read_pipeline_definition(medallion_file)

    checks = {c.name: c.action.value
              for c in pipeline.tables["clean_orders"].quality_checks}
    assert checks == {"id_present": "fail", "amount_positive": "log"}


def test_the_dependency_graph_and_execution_order_still_come_out(medallion_file):
    """`ref()` and `source()` are read out of the transform's returned SQL — the
    template engine always did this with `ast`, never by calling the function."""
    result = PipelineCompiler().validate_only(medallion_file)

    assert result.success, result.validation_errors
    graph = result.dependency_graph
    assert set(graph.nodes) == {"orders", "clean_orders", "daily_sales"}
    assert ("orders", "clean_orders") in graph.edges
    assert ("clean_orders", "daily_sales") in graph.edges
    batches = [set(b) for b in DependencyGraphBuilder.get_execution_order(graph)]
    assert batches == [{"clean_orders"}, {"daily_sales"}]


def test_compilation_still_produces_the_airflow_dag(medallion_file):
    result = PipelineCompiler().compile_file(medallion_file)

    assert result.success, result.validation_errors
    dag = next(c for t, c in result.artifacts if t == "airflow_dag")
    assert "datapond__medallion" in dag
    assert 'task_id="ingest__orders"' in dag
    assert 'task_id="transform__clean_orders"' in dag
    assert 'task_id="quality__clean_orders"' in dag
    # The transform SQL reached the generator, so it was read from the source.
    assert "# SQL: SELECT * FROM" in dag


def test_a_broken_pipeline_is_still_refused(tmp_path):
    """The reader applies the real decorators, so the DSL's own validation — here a
    processing mode that does not exist — still produces the same message."""
    path = tmp_path / "bad_mode.py"
    path.write_text('''
from app.pipelines.decorators import pipeline, live_table

@pipeline(name="bad", schedule="@daily")
def bad(): pass

@live_table(name="t", mode="occasionally")
def t():
    return "SELECT 1"
''')

    result = PipelineCompiler().validate_only(str(path))

    assert not result.success
    assert any("occasionally" in e for e in result.validation_errors), \
        result.validation_errors


def test_a_syntax_error_names_the_line(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("@pipeline(name='x'\ndef x(): pass\n")

    result = PipelineCompiler().validate_only(str(path))

    assert not result.success
    assert "Syntax error at line" in result.validation_errors[0]


def test_a_missing_pipeline_decorator_is_still_the_same_error(tmp_path):
    path = tmp_path / "no_pipeline.py"
    path.write_text('''
from app.pipelines.decorators import live_table

@live_table(name="t")
def t():
    return "SELECT 1"
''')

    result = PipelineCompiler().validate_only(str(path))

    assert not result.success
    assert "No pipeline defined" in result.validation_errors[0]


# ── the limits, reported rather than guessed ──────────────────────────────────

def test_a_computed_argument_is_refused_by_name(tmp_path):
    """A definition that can only be known by running the file is the one thing this
    reader will not guess at. It says so, naming the argument, instead of quietly
    reporting a pipeline that is missing a table."""
    path = tmp_path / "computed.py"
    path.write_text('''
import os
from app.pipelines.decorators import pipeline, live_table

@pipeline(name="computed", schedule="@daily")
def computed(): pass

@live_table(name=os.environ["TABLE_NAME"])
def t():
    return "SELECT 1"
''')

    result = PipelineCompiler().validate_only(str(path))

    assert not result.success
    message = result.validation_errors[0]
    assert "'name'" in message and "not a literal" in message


def test_an_unrecognised_decorator_is_reported_not_executed(tmp_path):
    """`@quality(table=...)` is what the pipeline builder emits for a quality check
    today, and `quality` is a class that takes no arguments — so importing this file
    used to fail outright. Reading it reports the decorator as ignored and describes
    the rest of the pipeline, which is the honest answer to 'what does this declare'."""
    path = tmp_path / "unknown_decorator.py"
    path.write_text('''
from app.pipelines.decorators import pipeline, source, live_table, quality

@pipeline(name="builder_output", schedule="@daily")
def builder_output(): pass

@source(name="raw", connection="conn1", table="public.raw")
def raw(): pass

@live_table(name="clean")
def clean():
    return "SELECT * FROM {{ source('raw') }}"

@quality(table="clean")
def check_clean(): return "id IS NOT NULL"
''')

    result = PipelineCompiler().validate_only(str(path))

    assert result.success, result.validation_errors
    assert any("not a DataPond pipeline decorator" in w for w in result.warnings), \
        result.warnings


def test_module_level_statements_are_reported_as_not_executed(tmp_path):
    path = tmp_path / "module_code.py"
    path.write_text('''
from app.pipelines.decorators import pipeline, source, live_table

SQL = "SELECT * FROM {{ source('raw') }}"

@pipeline(name="module_code", schedule="@daily")
def module_code(): pass

@source(name="raw", connection="conn1", table="public.raw")
def raw(): pass

@live_table(name="clean")
def clean():
    return "SELECT * FROM {{ source('raw') }}"
''')

    result = PipelineCompiler().validate_only(str(path))

    assert result.success, result.validation_errors
    assert any("not executed" in w for w in result.warnings), result.warnings
