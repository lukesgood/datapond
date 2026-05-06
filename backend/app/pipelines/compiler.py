"""
Pipeline compiler - converts decorated pipeline definitions into Airflow DAGs.
Main orchestrator for compilation process.
"""
import importlib.util
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

from .models import Pipeline, CompilationResult, DependencyGraph
from .decorators import LiveTableRegistry, get_pipeline_state
from .dependency_graph import DependencyGraphBuilder, PipelineValidationError
from .dag_generator import AirflowDagGenerator


class PipelineCompiler:
    """
    Main compiler for declarative pipelines.
    Coordinates discovery, validation, and code generation.
    """

    def __init__(self):
        self.dag_generator = AirflowDagGenerator()

    def compile_file(self, pipeline_file: str) -> CompilationResult:
        """
        Compile a pipeline from a Python file.

        Args:
            pipeline_file: Path to pipeline definition file

        Returns:
            CompilationResult with generated artifacts and metadata
        """
        # Reset registry
        LiveTableRegistry.reset()

        # Load pipeline module
        try:
            pipeline = self._load_pipeline_module(pipeline_file)
        except Exception as e:
            result = CompilationResult(pipeline_name="unknown")
            result.add_error(f"Failed to load pipeline: {e}")
            return result

        return self.compile_pipeline(pipeline, pipeline_file)

    def compile_pipeline(
        self,
        pipeline: Pipeline,
        source_file: Optional[str] = None
    ) -> CompilationResult:
        """
        Compile a pipeline definition.

        Args:
            pipeline: Pipeline definition from decorators
            source_file: Source file path (for metadata)

        Returns:
            CompilationResult with generated artifacts
        """
        result = CompilationResult(
            pipeline_name=pipeline.pipeline.name,
            compiled_at=datetime.utcnow()
        )

        # Step 1: Build dependency graph
        try:
            graph = DependencyGraphBuilder.build_graph(pipeline)
            result.dependency_graph = graph
        except Exception as e:
            result.add_error(f"Dependency graph construction failed: {e}")
            return result

        # Step 2: Validate graph
        validation_errors = DependencyGraphBuilder.validate_graph(graph)
        if validation_errors:
            for error in validation_errors:
                result.add_error(error)
            return result

        # Step 3: Check for warnings
        warnings = self._check_warnings(pipeline, graph)
        for warning in warnings:
            result.add_warning(warning)

        # Step 4: Generate Airflow DAG
        try:
            dag_code = self.dag_generator.generate_dag(
                pipeline=pipeline,
                graph=graph,
                source_file=source_file
            )
            result.add_artifact("airflow_dag", dag_code)
        except Exception as e:
            result.add_error(f"DAG generation failed: {e}")
            return result

        # Step 5: Validate pipeline references
        try:
            pipeline.validate_references()
        except Exception as e:
            result.add_error(f"Reference validation failed: {e}")
            return result

        return result

    def _load_pipeline_module(self, pipeline_file: str) -> Pipeline:
        """
        Load pipeline module and extract definitions.

        Args:
            pipeline_file: Path to pipeline Python file

        Returns:
            Pipeline definition

        Raises:
            Exception: If loading fails
        """
        file_path = Path(pipeline_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Pipeline file not found: {pipeline_file}")

        # Load module
        spec = importlib.util.spec_from_file_location("pipeline_module", file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {pipeline_file}")

        module = importlib.util.module_from_spec(spec)
        sys.modules["pipeline_module"] = module
        spec.loader.exec_module(module)

        # Get pipeline state from registry
        pipeline = get_pipeline_state()

        return pipeline

    def _check_warnings(self, pipeline: Pipeline, graph: DependencyGraph) -> list[str]:
        """
        Check for common issues and generate warnings.

        Returns:
            List of warning messages
        """
        warnings = []

        # Check for tables without quality checks
        for table_name, table_def in pipeline.tables.items():
            if not table_def.quality_checks:
                warnings.append(
                    f"Table '{table_name}' has no quality checks defined"
                )

        # Check for incremental tables without watermark column
        for table_name, table_def in pipeline.tables.items():
            if table_def.mode.value == "incremental" and not table_def.watermark_column:
                # Check if transform uses incremental_filter
                if table_def.transform_sql and "incremental_filter" in table_def.transform_sql:
                    warnings.append(
                        f"Table '{table_name}' uses incremental mode but no watermark_column specified"
                    )

        # Check for very deep dependency chains (>5 levels)
        batches = DependencyGraphBuilder.get_execution_order(graph)
        if len(batches) > 5:
            warnings.append(
                f"Deep dependency chain detected ({len(batches)} levels). "
                f"Consider flattening for better parallelism."
            )

        # Check for large fan-out (table with many dependents)
        for node_name, node in graph.nodes.items():
            if len(node.dependents) > 10:
                warnings.append(
                    f"Table '{node_name}' has many dependents ({len(node.dependents)}). "
                    f"Consider breaking into smaller tables."
                )

        return warnings

    def validate_only(self, pipeline_file: str) -> CompilationResult:
        """
        Validate pipeline without generating artifacts.

        Args:
            pipeline_file: Path to pipeline file

        Returns:
            CompilationResult with validation results
        """
        # Reset registry
        LiveTableRegistry.reset()

        result = CompilationResult(pipeline_name="validation")

        # Load pipeline
        try:
            pipeline = self._load_pipeline_module(pipeline_file)
            result.pipeline_name = pipeline.pipeline.name
        except Exception as e:
            result.add_error(f"Failed to load pipeline: {e}")
            return result

        # Build and validate graph
        try:
            graph = DependencyGraphBuilder.build_graph(pipeline)
            result.dependency_graph = graph

            validation_errors = DependencyGraphBuilder.validate_graph(graph)
            if validation_errors:
                for error in validation_errors:
                    result.add_error(error)
        except Exception as e:
            result.add_error(f"Validation failed: {e}")
            return result

        # Check warnings
        warnings = self._check_warnings(pipeline, graph)
        for warning in warnings:
            result.add_warning(warning)

        return result


# Convenience function for direct compilation
def compile_pipeline_file(pipeline_file: str) -> CompilationResult:
    """
    Compile a pipeline file.

    Args:
        pipeline_file: Path to pipeline Python file

    Returns:
        CompilationResult
    """
    compiler = PipelineCompiler()
    return compiler.compile_file(pipeline_file)
