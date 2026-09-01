"""A quality check configured in the console has to reach the compiled pipeline.

It never did. Both builders emitted a decorator the DSL has never defined:

    @quality(table="bronze_orders")
    def check_bronze_orders(): return "amount > 0"

`app/pipelines/decorators.py` defines `quality` as a namespace — `quality.expect`,
`quality.expect_or_drop`, `quality.expect_or_fail` — and those attach to a table by
decorating **the same function** `@live_table` decorates, below it. Decorators apply
bottom-up, so the check is pending on the function when `live_table` reads it. A
separate `check_*` function attaches to nothing even if `quality(...)` were callable.

So every check anyone typed into the console was dropped. It used to be loud: importing
the submitted module raised `TypeError: quality() takes no arguments` and validation
failed. Since the compiler started parsing instead of importing (the fix that stopped
submitted Python running inside the backend), it is quiet — validation succeeds, a note
says an unrecognized decorator was ignored, and the pipeline has no checks.

This file is the backend half of the fix. `frontend/lib/pipeline-quality.ts` writes the
decorator and `frontend/lib/pipeline-quality.test.ts` pins the exact string; the module
below runs that string through the real compiler and asserts the check arrives. Both
sides quote the same literal deliberately: change one and the other fails.

What this does NOT claim: that a violated check stops anything at run time.
`dag_generator._generate_quality_task` emits a `PythonOperator` bound to
`_not_implemented` with the checks listed as comments, and `/pipelines/deploy` refuses
with 501 regardless. The check now reaches the compiled artifact, which is what was
broken; executing it is the placeholder the rest of that feature already is.
"""
from app.pipelines.compiler import PipelineCompiler
from app.pipelines.decorators import LiveTableRegistry
from app.pipelines.models import QualityAction


# Exactly what frontend/lib/pipeline-quality.ts + the two builders now emit. Kept as a
# literal rather than generated, because the point is that the two languages agree on
# one string.
BUILDER_OUTPUT = '''
from app.pipelines.decorators import pipeline, source, live_table, quality


@pipeline(name="sales", schedule="@daily")
def sales_pipeline():
    pass


@source(
    name="raw_orders",
    connection="warehouse",
    source_type="postgres",
    table="orders",
    mode="full_refresh",
)
def raw_orders():
    pass


@live_table(
    name="bronze_orders",
    mode="incremental",
    depends_on=["raw_orders"],
)
@quality.expect_or_fail("bronze_orders_quality", "amount > 0")
def bronze_orders():
    return """
    SELECT * FROM {{ source('raw_orders') }}
    """
'''

# The shape that shipped for months. Kept so the defect stays legible: this is not a
# hypothetical, it is what the console wrote into every pipeline with a check.
DEAD_FORM = '''
from app.pipelines.decorators import pipeline, source, live_table, quality


@pipeline(name="sales", schedule="@daily")
def sales_pipeline():
    pass


@source(
    name="raw_orders",
    connection="warehouse",
    source_type="postgres",
    table="orders",
    mode="full_refresh",
)
def raw_orders():
    pass


@live_table(
    name="bronze_orders",
    mode="incremental",
    depends_on=["raw_orders"],
)
def bronze_orders():
    return """
    SELECT * FROM {{ source('raw_orders') }}
    """


@quality(table="bronze_orders")
def check_bronze_orders(): return "amount > 0"
'''


def _compile(source: str, tmp_path):
    """(result, tables) — the compilation result and the table definitions it built.

    `CompilationResult` carries artifacts and errors, not the tables, and the registry
    is where the compiler leaves them. Both are needed: the checks live on the table,
    and the DAG is an artifact.
    """
    path = tmp_path / "pipeline_def.py"
    path.write_text(source)
    compiler = PipelineCompiler()
    result = compiler.compile_file(str(path))
    # compile_file resets the registry and reads into it, so the tables it built are
    # sitting there afterwards. Reading the file a second time would re-register the
    # pipeline and raise "Pipeline already defined" — the registry is deliberately
    # single-occupancy.
    return result, LiveTableRegistry.get_tables()


def _dag(result) -> str:
    return "\n".join(content for kind, content in result.artifacts if "dag" in kind.lower())


def test_a_configured_check_reaches_the_table_definition(tmp_path):
    """The whole point of the fix: the console's condition is on the table."""
    result, tables = _compile(BUILDER_OUTPUT, tmp_path)
    assert result.success, result.validation_errors

    table = tables["bronze_orders"]
    assert len(table.quality_checks) == 1, (
        "the builder's quality check did not reach the compiled table")
    check = table.quality_checks[0]
    assert check.condition == "amount > 0"
    assert check.name == "bronze_orders_quality"


def test_the_action_is_the_one_the_console_promises():
    """The field's help text says "halts on failure", so the emitted decorator is
    `expect_or_fail` — `QualityAction.FAIL`. `expect` logs and `expect_or_drop` filters
    rows, and either would quietly turn the console's promise into a different one."""
    import inspect

    from pathlib import Path

    helper = (Path(__file__).resolve().parents[2]
              / "frontend/lib/pipeline-quality.ts").read_text()
    assert "expect_or_fail" in helper, (
        "the frontend helper no longer writes the action the console promises")
    # That the helper stopped *emitting* the dead form is pinned on the frontend side
    # (lib/pipeline-quality.test.ts, plus the scan over both builders) — asserting it
    # here would only catch the prose in this file's own docstring, which quotes it.
    from app.pipelines.decorators import quality
    assert callable(quality.expect_or_fail)


def test_the_compiled_check_carries_the_failing_action(tmp_path):
    _result, tables = _compile(BUILDER_OUTPUT, tmp_path)
    check = tables["bronze_orders"].quality_checks[0]
    assert check.action is QualityAction.FAIL


def test_the_generated_dag_contains_the_check(tmp_path):
    """A check on the table definition that never reaches the DAG would be the same
    defect one step later."""
    result, _tables = _compile(BUILDER_OUTPUT, tmp_path)
    dag = _dag(result)
    assert "quality__bronze_orders" in dag
    assert "amount > 0" in dag


def test_the_shape_that_shipped_produces_no_check_at_all(tmp_path):
    """The defect, kept as a test so it cannot come back quietly.

    Note what this asserts: not that compilation fails, but that it *succeeds* and
    silently produces nothing — which is why nobody noticed. The parser records a note
    about the unrecognized decorator; the table has no checks.
    """
    result, tables = _compile(DEAD_FORM, tmp_path)
    assert result.success, "the dead form does not even fail loudly"
    assert tables["bronze_orders"].quality_checks == []
    assert any("quality" in warning.lower() for warning in result.warnings), (
        "the ignored decorator is not even mentioned")


def test_a_table_with_no_condition_has_no_check(tmp_path):
    """The console omits the decorator entirely when the field is blank; nothing
    should invent an empty check."""
    source = BUILDER_OUTPUT.replace(
        '@quality.expect_or_fail("bronze_orders_quality", "amount > 0")\n', "")
    result, tables = _compile(source, tmp_path)
    assert result.success, result.validation_errors
    assert tables["bronze_orders"].quality_checks == []
