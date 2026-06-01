"""
Unit tests for pipeline decorators.
"""
import pytest
from app.pipelines.decorators import (
    pipeline, source, live_table, quality,
    LiveTableRegistry
)
from app.pipelines.models import ProcessingMode, Engine, QualityAction


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before each test"""
    LiveTableRegistry.reset()
    yield
    LiveTableRegistry.reset()


def test_pipeline_decorator():
    """Test @pipeline decorator"""
    @pipeline(
        name="test_pipeline",
        schedule="@daily",
        tags=["test"],
        owner="test@example.com"
    )
    def my_pipeline():
        """Test pipeline"""
        pass

    pipeline_def = LiveTableRegistry.get_pipeline()

    assert pipeline_def is not None
    assert pipeline_def.name == "test_pipeline"
    assert pipeline_def.schedule == "@daily"
    assert pipeline_def.tags == ["test"]
    assert pipeline_def.owner == "test@example.com"
    assert pipeline_def.description == "Test pipeline"


def test_source_decorator():
    """Test @source decorator"""
    @source(
        name="raw_data",
        connection="postgres",
        table="public.data",
        mode="incremental",
        watermark_column="updated_at"
    )
    def raw_data_source():
        """Raw data source"""
        pass

    source_def = LiveTableRegistry.get_source("raw_data")

    assert source_def is not None
    assert source_def.name == "raw_data"
    assert source_def.connection_id == "postgres"
    assert source_def.table == "public.data"
    assert source_def.mode == ProcessingMode.INCREMENTAL
    assert source_def.watermark_column == "updated_at"


def test_live_table_decorator():
    """Test @live_table decorator"""
    @live_table(
        name="clean_data",
        comment="Cleaned data",
        mode="incremental",
        partition_by=["date"]
    )
    def clean_data():
        """Clean data"""
        return "SELECT * FROM raw_data"

    table_def = LiveTableRegistry.get_table("clean_data")

    assert table_def is not None
    assert table_def.name == "clean_data"
    assert table_def.comment == "Cleaned data"
    assert table_def.mode == ProcessingMode.INCREMENTAL
    assert table_def.partition_by == ["date"]


def test_quality_decorators():
    """Test quality check decorators"""
    @live_table(name="test_table")
    @quality.expect("check1", "amount > 0")
    @quality.expect_or_drop("check2", "status = 'valid'")
    @quality.expect_or_fail("check3", "id IS NOT NULL")
    def test_table():
        return "SELECT * FROM data"

    table_def = LiveTableRegistry.get_table("test_table")

    assert len(table_def.quality_checks) == 3

    checks = {c.name: c for c in table_def.quality_checks}

    assert checks["check1"].action == QualityAction.LOG
    assert checks["check1"].condition == "amount > 0"

    assert checks["check2"].action == QualityAction.DROP
    assert checks["check2"].condition == "status = 'valid'"

    assert checks["check3"].action == QualityAction.FAIL
    assert checks["check3"].condition == "id IS NOT NULL"


def test_duplicate_table_error():
    """Test that duplicate table names raise error"""
    @live_table(name="dup_table")
    def table1():
        return "SELECT 1"

    with pytest.raises(ValueError, match="already registered"):
        @live_table(name="dup_table")
        def table2():
            return "SELECT 2"


def test_quality_without_live_table_ignored():
    """Test that quality decorator without @live_table just stores pending checks"""
    @quality.expect("test", "1=1")
    def not_a_table():
        pass

    # Should have pending checks but not be registered as a table
    assert hasattr(not_a_table, '_pending_quality_checks')
    assert len(not_a_table._pending_quality_checks) == 1
    assert LiveTableRegistry.get_table("not_a_table") is None


def test_connection_alias():
    """Test that 'connection' and 'connection_id' are aliases"""
    @source(
        name="test_source",
        connection="my_connection",
        table="data"
    )
    def test_source():
        pass

    source_def = LiveTableRegistry.get_source("test_source")
    assert source_def.connection_id == "my_connection"


def test_invalid_schedule():
    """Test invalid cron schedule"""
    with pytest.raises(ValueError, match="Schedule must be"):
        @pipeline(
            name="bad_pipeline",
            schedule="not_a_schedule"
        )
        def bad_pipeline():
            pass
