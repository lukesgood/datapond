"""
Pipeline compiler - converts decorated pipeline definitions into Airflow DAGs.
Main orchestrator for compilation process.
"""
from pathlib import Path
from typing import Optional
from datetime import datetime

from .models import Pipeline, CompilationResult, DependencyGraph
from .decorators import LiveTableRegistry
from .dependency_graph import DependencyGraphBuilder, PipelineValidationError
from .dag_generator import AirflowDagGenerator
from .ast_reader import read_pipeline_source


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

        # Read the pipeline definition (parsed, never executed)
        try:
            pipeline, notes = self._read_pipeline_definition(pipeline_file)
        except Exception as e:
            result = CompilationResult(pipeline_name="unknown")
            result.add_error(f"Failed to load pipeline: {e}")
            return result

        result = self.compile_pipeline(pipeline, pipeline_file)
        for note in notes:
            result.add_warning(note)
        return result

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

    def _read_pipeline_definition(
        self,
        pipeline_file: str
    ) -> tuple[Pipeline, list[str]]:
        """
        Read the pipeline a file declares, without running the file.

        This used to import the file — `spec.loader.exec_module` — so every top-level
        statement in it ran inside this process. `/pipelines/validate` and
        `/pipelines/compile` accept that file in a request body, which made "describe
        this pipeline" and "execute arbitrary code as the backend" the same operation.
        The DSL is declarative, so the definition is read with `ast` instead; see
        `app/pipelines/ast_reader.py`.

        Args:
            pipeline_file: Path to pipeline Python file

        Returns:
            (Pipeline definition, notes about anything the reader could not use)

        Raises:
            Exception: If the file cannot be read or does not declare a pipeline
        """
        file_path = Path(pipeline_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Pipeline file not found: {pipeline_file}")

        return read_pipeline_source(
            file_path.read_text(encoding="utf-8"), str(file_path))

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

        # Read the pipeline definition (parsed, never executed)
        try:
            pipeline, notes = self._read_pipeline_definition(pipeline_file)
            result.pipeline_name = pipeline.pipeline.name
            for note in notes:
                result.add_warning(note)
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
