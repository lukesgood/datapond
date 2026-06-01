"""
Unit tests for pipeline compiler.
"""
import pytest
from pathlib import Path
from app.pipelines.compiler import PipelineCompiler
from app.pipelines.decorators import LiveTableRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before each test"""
    LiveTableRegistry.reset()
    yield
    LiveTableRegistry.reset()


def test_compile_example_sales_pipeline():
    """Test compiling the example sales pipeline"""
    # Get path to example pipeline
    example_file = Path(__file__).parent.parent.parent / "examples" / "pipelines" / "example_sales.py"

    if not example_file.exists():
        pytest.skip(f"Example file not found: {example_file}")

    compiler = PipelineCompiler()
    result = compiler.compile_file(str(example_file))

    # Check compilation success
    assert result.success, f"Compilation failed: {result.validation_errors}"
    assert result.pipeline_name == "example_sales_analytics"

    # Check artifacts generated
    assert len(result.artifacts) > 0
    artifact_types = [a[0] for a in result.artifacts]
    assert "airflow_dag" in artifact_types

    # Check DAG code
    dag_code = result.artifacts[0][1]
    assert "datapond__example_sales_analytics" in dag_code
    assert "default_args" in dag_code
    assert "with DAG" in dag_code

    # Check dependency graph
    assert result.dependency_graph is not None
    assert len(result.dependency_graph.nodes) > 0

    # Check for expected tables
    node_names = list(result.dependency_graph.nodes.keys())
    assert "raw_sales" in node_names
    assert "clean_sales" in node_names
    assert "daily_sales_summary" in node_names


def test_validation_only():
    """Test validation without compilation"""
    example_file = Path(__file__).parent.parent.parent / "examples" / "pipelines" / "example_sales.py"

    if not example_file.exists():
        pytest.skip(f"Example file not found: {example_file}")

    compiler = PipelineCompiler()
    result = compiler.validate_only(str(example_file))

    # Should succeed
    assert result.success
    assert result.pipeline_name == "example_sales_analytics"

    # Should have dependency graph but no artifacts
    assert result.dependency_graph is not None
    assert len(result.artifacts) == 0


def test_compile_invalid_file():
    """Test compiling non-existent file"""
    compiler = PipelineCompiler()
    result = compiler.compile_file("nonexistent.py")

    assert not result.success
    assert len(result.validation_errors) > 0
    assert "not found" in result.validation_errors[0].lower()


def test_circular_dependency_detection(tmp_path):
    """Test detection of circular dependencies"""
    # Create pipeline with circular dependency
    pipeline_file = tmp_path / "circular.py"
    pipeline_file.write_text("""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from app.pipelines import pipeline, live_table

@pipeline(name="circular_test", schedule="@daily")

@live_table(name="table_a")
def table_a():
    return "SELECT * FROM {{ ref('table_b') }}"

@live_table(name="table_b")
def table_b():
    return "SELECT * FROM {{ ref('table_a') }}"
""")

    compiler = PipelineCompiler()
    result = compiler.compile_file(str(pipeline_file))

    # Should fail with circular dependency error
    assert not result.success
    assert any("circular" in err.lower() for err in result.validation_errors)


def test_missing_reference_detection(tmp_path):
    """Test detection of missing table references"""
    pipeline_file = tmp_path / "missing_ref.py"
    pipeline_file.write_text("""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from app.pipelines import pipeline, live_table

@pipeline(name="missing_ref_test", schedule="@daily")

@live_table(name="table_a")
def table_a():
    return "SELECT * FROM {{ ref('nonexistent_table') }}"
""")

    compiler = PipelineCompiler()
    result = compiler.compile_file(str(pipeline_file))

    # Should fail with missing reference error
    assert not result.success
    assert any("unknown" in err.lower() or "not found" in err.lower()
               for err in result.validation_errors)


def test_warnings_for_no_quality_checks(tmp_path):
    """Test warning generation for tables without quality checks"""
    pipeline_file = tmp_path / "no_quality.py"
    pipeline_file.write_text("""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from app.pipelines import pipeline, source, live_table

@pipeline(name="no_quality_test", schedule="@daily")

@source(name="raw", connection="postgres", table="data")
def raw_source():
    pass

@live_table(name="table_no_checks")
def table_no_checks():
    return "SELECT * FROM {{ source('raw') }}"
""")

    compiler = PipelineCompiler()
    result = compiler.compile_file(str(pipeline_file))

    # Should succeed but have warnings
    assert result.success
    assert len(result.warnings) > 0
    assert any("quality check" in warn.lower() for warn in result.warnings)
