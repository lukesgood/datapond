"""
DataPond Declarative Pipeline Framework

Provides Delta Live Tables-like functionality for DataPond:
- Declarative Python DSL with decorators
- Automatic dependency resolution
- Data quality constraints
- Incremental processing
- Airflow DAG generation

Usage:
    from datapond.pipelines import pipeline, source, live_table, quality

    @pipeline(name="my_pipeline", schedule="@daily")

    @source(name="raw_data", connection="postgres", table="orders")
    def raw_data_source():
        pass

    @live_table(name="clean_data", mode="incremental")
    @quality.expect_or_fail("non_null_id", "id IS NOT NULL")
    def clean_data():
        return '''
            SELECT * FROM {{ source('raw_data') }}
            WHERE {{ incremental_filter('updated_at') }}
        '''
"""

# Public API exports
from .decorators import (
    pipeline,
    source,
    live_table,
    quality,
    LiveTableRegistry,
    get_pipeline_state
)

from .models import (
    Pipeline,
    PipelineDefinition,
    TableDefinition,
    SourceDefinition,
    QualityCheck,
    QualityAction,
    ProcessingMode,
    Engine,
    DependencyGraph,
    CompilationResult
)

from .compiler import (
    PipelineCompiler,
    compile_pipeline_file
)

from .dependency_graph import (
    DependencyGraphBuilder,
    PipelineValidationError
)

from .templates import (
    template_engine,
    extract_sql_from_function
)

__version__ = "0.1.0"

__all__ = [
    # Decorators (main user API)
    "pipeline",
    "source",
    "live_table",
    "quality",

    # Compilation
    "PipelineCompiler",
    "compile_pipeline_file",

    # Models
    "Pipeline",
    "PipelineDefinition",
    "TableDefinition",
    "SourceDefinition",
    "QualityCheck",
    "DependencyGraph",
    "CompilationResult",

    # Enums
    "QualityAction",
    "ProcessingMode",
    "Engine",

    # Internal (advanced usage)
    "LiveTableRegistry",
    "get_pipeline_state",
    "DependencyGraphBuilder",
    "PipelineValidationError",
    "template_engine",
    "extract_sql_from_function",
]
