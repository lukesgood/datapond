"""
CLI tool for DataPond declarative pipelines.

Commands:
    datapond pipeline validate <file>  - Validate pipeline definition
    datapond pipeline compile <file>   - Compile to Airflow DAG
    datapond pipeline list             - List deployed pipelines
    datapond pipeline status <name>    - Get pipeline status
"""
import sys
import argparse
from pathlib import Path
from typing import Optional

from .compiler import PipelineCompiler
from .dependency_graph import DependencyGraphBuilder


def validate_command(args):
    """Validate pipeline without deploying"""
    print(f"Validating pipeline: {args.file}")
    print("=" * 60)

    compiler = PipelineCompiler()
    result = compiler.validate_only(args.file)

    if result.success:
        print("✓ Pipeline validation successful!")
        print(f"\nPipeline: {result.pipeline_name}")

        if result.dependency_graph:
            # Show graph visualization
            graph_viz = DependencyGraphBuilder.visualize_graph(result.dependency_graph)
            print(f"\n{graph_viz}")

            # Show execution order
            batches = DependencyGraphBuilder.get_execution_order(result.dependency_graph)
            print(f"\nExecution plan: {len(batches)} batch(es)")

        if result.warnings:
            print(f"\n⚠ Warnings ({len(result.warnings)}):")
            for warning in result.warnings:
                print(f"  - {warning}")

        return 0
    else:
        print("✗ Pipeline validation failed!")
        print(f"\nErrors ({len(result.validation_errors)}):")
        for error in result.validation_errors:
            print(f"  - {error}")
        return 1


def compile_command(args):
    """Compile pipeline to Airflow DAG"""
    print(f"Compiling pipeline: {args.file}")
    print("=" * 60)

    compiler = PipelineCompiler()
    result = compiler.compile_file(args.file)

    if result.success:
        print("✓ Pipeline compiled successfully!")
        print(f"\nPipeline: {result.pipeline_name}")

        # Show artifacts
        print(f"\nGenerated artifacts ({len(result.artifacts)}):")
        for artifact_type, content in result.artifacts:
            print(f"  - {artifact_type}: {len(content)} bytes")

        # Save to output file
        output_file = args.output or f"{result.pipeline_name}.py"
        output_path = Path(output_file)

        if result.artifacts:
            # Write first artifact (Airflow DAG)
            artifact_type, content = result.artifacts[0]
            output_path.write_text(content)
            print(f"\n✓ Saved to: {output_path.absolute()}")

        # Show warnings
        if result.warnings:
            print(f"\n⚠ Warnings ({len(result.warnings)}):")
            for warning in result.warnings:
                print(f"  - {warning}")

        return 0
    else:
        print("✗ Pipeline compilation failed!")
        print(f"\nErrors ({len(result.validation_errors)}):")
        for error in result.validation_errors:
            print(f"  - {error}")
        return 1


def list_command(args):
    """List deployed pipelines"""
    print("Deployed Pipelines:")
    print("=" * 60)
    print("(Not implemented yet - requires Airflow API integration)")
    print("\nUpcoming features:")
    print("  - List all deployed pipelines")
    print("  - Show status and last run")
    print("  - Filter by tag or owner")
    return 0


def status_command(args):
    """Get pipeline status"""
    print(f"Pipeline Status: {args.name}")
    print("=" * 60)
    print("(Not implemented yet - requires Airflow API integration)")
    print("\nUpcoming features:")
    print("  - Current run status")
    print("  - Recent run history")
    print("  - Quality check results")
    print("  - Lineage graph")
    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="DataPond Pipeline Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate a pipeline
  datapond pipeline validate examples/pipelines/example_sales.py

  # Compile to Airflow DAG
  datapond pipeline compile examples/pipelines/example_sales.py

  # Compile with custom output path
  datapond pipeline compile examples/pipelines/example_sales.py -o /opt/airflow/dags/sales.py

  # List deployed pipelines
  datapond pipeline list

  # Get pipeline status
  datapond pipeline status example_sales_analytics
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Validate command
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate pipeline definition"
    )
    validate_parser.add_argument("file", help="Pipeline Python file")
    validate_parser.set_defaults(func=validate_command)

    # Compile command
    compile_parser = subparsers.add_parser(
        "compile",
        help="Compile pipeline to Airflow DAG"
    )
    compile_parser.add_argument("file", help="Pipeline Python file")
    compile_parser.add_argument(
        "-o", "--output",
        help="Output file path (default: <pipeline_name>.py)"
    )
    compile_parser.set_defaults(func=compile_command)

    # List command
    list_parser = subparsers.add_parser(
        "list",
        help="List deployed pipelines"
    )
    list_parser.set_defaults(func=list_command)

    # Status command
    status_parser = subparsers.add_parser(
        "status",
        help="Get pipeline status"
    )
    status_parser.add_argument("name", help="Pipeline name")
    status_parser.set_defaults(func=status_command)

    # Parse and execute
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        if "--debug" in sys.argv:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
