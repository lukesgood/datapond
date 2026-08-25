"""
Airflow DAG code generator.
Converts pipeline definitions into executable Airflow DAG Python code.
"""
from typing import Optional, List
from datetime import datetime, timedelta
import textwrap

from .models import Pipeline, DependencyGraph, TableDefinition, QualityCheck, QualityAction
from .dependency_graph import DependencyGraphBuilder


UNIMPLEMENTED_MARKER = "DATAPOND_UNIMPLEMENTED_TASKS"


def unimplemented_tasks(dag_code: str) -> List[str]:
    """Task ids in `dag_code` that stand in for work nobody has written.

    Read from a marker the generator emits rather than guessed from the operator
    names: the question is what this DAG will actually do, and a regex over source
    text answers a different, easier question.

    Fails closed. A marker that cannot be parsed returns a non-empty list, because a
    marker we cannot read is not evidence that the tasks work.
    """
    import ast

    for line in dag_code.splitlines():
        if line.startswith(UNIMPLEMENTED_MARKER):
            try:
                value = ast.literal_eval(line.split("=", 1)[1].strip())
                return list(value)
            except Exception:
                return ["<unparseable>"]
    return []



class AirflowDagGenerator:
    """
    Generates Airflow DAG Python code from pipeline definitions.
    """

    def generate_dag(
        self,
        pipeline: Pipeline,
        graph: DependencyGraph,
        source_file: Optional[str] = None
    ) -> str:
        """
        Generate complete Airflow DAG Python file.

        Args:
            pipeline: Pipeline definition
            graph: Dependency graph
            source_file: Source file path (for metadata)

        Returns:
            Python code as string
        """
        lines = []

        # Header
        lines.extend(self._generate_header(pipeline, source_file))

        # Imports
        lines.extend(self._generate_imports())

        # DAG configuration
        lines.extend(self._generate_dag_config(pipeline))

        # DAG definition
        lines.append("with DAG(")
        lines.append(f'    dag_id="datapond__{pipeline.pipeline.name}",')
        lines.append("    default_args=default_args,")
        lines.append(f'    schedule_interval="{pipeline.pipeline.schedule}",')
        lines.append("    start_date=days_ago(1),")
        lines.append("    catchup=False,")
        tags = ["datapond-pipeline"] + pipeline.pipeline.tags
        lines.append(f"    tags={tags},")
        lines.append("    doc_md=__doc__,")
        lines.append(") as dag:")
        lines.append("")

        # Source ingestion tasks
        lines.extend(self._generate_source_tasks(pipeline))

        # Table transformation tasks
        lines.extend(self._generate_table_tasks(pipeline, graph))

        # Dependencies
        lines.extend(self._generate_dependencies(graph))

        code = "\n".join(lines)
        # Declare, at module level, which tasks stand in for work nobody wrote. The
        # deploy endpoint reads this rather than inferring from operator names: what
        # matters is whether this DAG will do anything, and that is a claim the
        # generator is the only thing in a position to make honestly.
        import re as _re
        placeholders = sorted(set(_re.findall(
            r'op_args=\["([^"]+)", "(?:source ingestion|quality checks|transform|'
            r'incremental checkpoint)"\]', code)))
        return f"{UNIMPLEMENTED_MARKER} = {placeholders!r}\n\n{code}"

    def _generate_header(
        self,
        pipeline: Pipeline,
        source_file: Optional[str]
    ) -> List[str]:
        """Generate file header with metadata"""
        now = datetime.utcnow().isoformat() + "Z"
        source_info = f"Source: {source_file}" if source_file else "Source: unknown"

        return [
            '"""',
            f'DataPond Pipeline: {pipeline.pipeline.name}',
            "",
            f"{pipeline.pipeline.description or 'Auto-generated pipeline'}",
            "",
            f"Generated: {now}",
            f"{source_info}",
            "Compiler: DataPond Pipeline Compiler v0.1.0",
            "",
            "DO NOT EDIT MANUALLY - Changes will be overwritten on next deployment",
            '"""',
            "",
        ]

    def _generate_imports(self) -> List[str]:
        """Generate import statements"""
        return [
            "from airflow import DAG",
            "from airflow.utils.dates import days_ago",
            "from airflow.operators.python import PythonOperator",
            "from datetime import timedelta",
            "",
            "",
            "def _not_implemented(task, detail):",
            "    \"\"\"Stand-in for a DataPond operator that does not exist yet.",
            "",
            "    Deliberately raises. The previous generator emitted EmptyOperator,",
            "    which succeeds — so every run went green having moved no data and",
            "    checked no quality rule, and Airflow's own status page became the",
            "    thing telling the operator it had worked.",
            "    \"\"\"",
            "    raise NotImplementedError(",
            "        f\"{task}: {detail}. This pipeline was compiled with placeholder \"",
            "        f\"tasks; the DataPond operator it needs is not implemented.\")",
            "",
            "",
            "# DataPond operators (to be implemented)",
            "# from datapond.operators import (",
            "#     TrinoOperator,",
            "#     QualityCheckOperator,",
            "#     SourceIngestOperator,",
            "#     IncrementalCheckpointOperator,",
            "#     LineageEmitOperator",
            "# )",
            "",
        ]

    def _generate_dag_config(self, pipeline: Pipeline) -> List[str]:
        """Generate DAG configuration"""
        p = pipeline.pipeline
        lines = [
            "# DAG Configuration",
            "default_args = {",
            f'    "owner": "{p.owner}",',
            f'    "retries": {p.max_retries},',
            f'    "retry_delay": timedelta(minutes={p.retry_delay_minutes}),',
            '    "depends_on_past": False,',
        ]

        # Email alert configuration
        if p.alert_on_failure and p.alert_email:
            # Parse comma-separated addresses into Python list
            emails = [e.strip() for e in p.alert_email.split(",") if e.strip()]
            lines.append(f'    "email": {emails},')
            lines.append('    "email_on_failure": True,')
            lines.append('    "email_on_retry": False,')
        else:
            lines.append('    "email_on_failure": False,')
            lines.append('    "email_on_retry": False,')

        lines += ["}", ""]
        return lines

    def _generate_source_tasks(self, pipeline: Pipeline) -> List[str]:
        """Generate source ingestion tasks"""
        if not pipeline.sources:
            return ["    # No sources defined", ""]

        lines = ["    # === Source Ingestion Tasks ===", ""]

        for source_name, source_def in pipeline.sources.items():
            task_id = f"ingest__{source_name}"

            lines.append(f"    # Source: {source_name}")
            lines.append(f"    {task_id} = PythonOperator(")
            lines.append(f'        task_id="{task_id}",')
            lines.append(f'        python_callable=_not_implemented,')
            lines.append(f'        op_args=["{task_id}", "source ingestion"],')
            lines.append(f'        # TODO: Replace with SourceIngestOperator')
            lines.append(f'        # connection_id="{source_def.connection_id}",')
            lines.append(f'        # source_table="{source_def.table}",')
            lines.append(f'        # target_table="{source_def.get_fqn()}",')
            lines.append(f'        # mode="{source_def.mode.value}",')
            if source_def.watermark_column:
                lines.append(f'        # watermark_column="{source_def.watermark_column}",')
            lines.append("    )")
            lines.append("")

        return lines

    def _generate_table_tasks(
        self,
        pipeline: Pipeline,
        graph: DependencyGraph
    ) -> List[str]:
        """Generate table transformation tasks"""
        if not pipeline.tables:
            return ["    # No tables defined", ""]

        lines = ["    # === Table Transformation Tasks ===", ""]

        for table_name, table_def in pipeline.tables.items():
            lines.extend(self._generate_single_table_tasks(table_name, table_def, pipeline))

        return lines

    def _generate_single_table_tasks(
        self,
        table_name: str,
        table_def: TableDefinition,
        pipeline: Pipeline
    ) -> List[str]:
        """Generate tasks for a single table"""
        lines = [f"    # Table: {table_name}"]

        # Quality check task (pre-transform)
        if table_def.quality_checks:
            lines.extend(self._generate_quality_task(table_name, table_def))

        # Main transform task
        lines.extend(self._generate_transform_task(table_name, table_def, pipeline))

        # Checkpoint task (for incremental tables)
        if table_def.mode.value == "incremental":
            lines.extend(self._generate_checkpoint_task(table_name, table_def))

        lines.append("")
        return lines

    def _generate_quality_task(
        self,
        table_name: str,
        table_def: TableDefinition
    ) -> List[str]:
        """Generate quality check task"""
        task_id = f"quality__{table_name}"

        lines = [f"    {task_id} = PythonOperator("]
        lines.append(f'        task_id="{task_id}",')
        lines.append(f'        python_callable=_not_implemented,')
        lines.append(f'        op_args=["{task_id}", "quality checks"],')
        lines.append(f'        # TODO: Replace with QualityCheckOperator')

        # Add quality checks as comments for now
        for check in table_def.quality_checks:
            lines.append(
                f'        # Check: {check.name} - {check.condition} ({check.action.value})'
            )

        lines.append("    )")
        lines.append("")

        return lines

    def _generate_transform_task(
        self,
        table_name: str,
        table_def: TableDefinition,
        pipeline: Pipeline
    ) -> List[str]:
        """Generate main transformation task"""
        task_id = f"transform__{table_name}"

        lines = [f"    {task_id} = PythonOperator("]
        lines.append(f'        task_id="{task_id}",')
        lines.append(f'        python_callable=_not_implemented,')
        lines.append(f'        op_args=["{task_id}", "transform"],')
        lines.append(f'        # TODO: Replace with TrinoOperator or PythonTransformOperator')
        lines.append(f'        # engine="{table_def.engine.value}",')
        lines.append(f'        # target_table="{table_def.get_fqn()}",')
        lines.append(f'        # mode="{table_def.mode.value}",')

        # Add SQL as comment (truncated)
        if table_def.transform_sql:
            sql_preview = table_def.transform_sql[:100].replace("\n", " ")
            lines.append(f'        # SQL: {sql_preview}...')

        lines.append("    )")
        lines.append("")

        return lines

    def _generate_checkpoint_task(
        self,
        table_name: str,
        table_def: TableDefinition
    ) -> List[str]:
        """Generate checkpoint task for incremental tables"""
        task_id = f"checkpoint__{table_name}"

        lines = [f"    {task_id} = PythonOperator("]
        lines.append(f'        task_id="{task_id}",')
        lines.append(f'        python_callable=_not_implemented,')
        lines.append(f'        op_args=["{task_id}", "incremental checkpoint"],')
        lines.append(f'        # TODO: Replace with IncrementalCheckpointOperator')
        lines.append(f'        # table="{table_def.get_fqn()}",')
        if table_def.watermark_column:
            lines.append(f'        # watermark_column="{table_def.watermark_column}",')
        lines.append("    )")
        lines.append("")

        return lines

    def _generate_dependencies(self, graph: DependencyGraph) -> List[str]:
        """Generate task dependencies"""
        lines = ["    # === Task Dependencies ===", ""]

        # Get execution batches
        batches = DependencyGraphBuilder.get_execution_order(graph)

        # Generate dependencies for each edge
        for from_name, to_name in graph.edges:
            from_node = graph.nodes[from_name]
            to_node = graph.nodes[to_name]

            # Determine task IDs
            if from_node.type == "source":
                from_task = f"ingest__{from_name}"
            else:
                from_task = f"transform__{from_name}"

            # For target, add quality check if exists
            if to_node.type == "table" and to_node.definition.quality_checks:
                # from -> quality -> transform
                quality_task = f"quality__{to_name}"
                transform_task = f"transform__{to_name}"

                lines.append(f"    {from_task} >> {quality_task} >> {transform_task}")

                # Add checkpoint if incremental
                if to_node.definition.mode.value == "incremental":
                    checkpoint_task = f"checkpoint__{to_name}"
                    lines.append(f"    {transform_task} >> {checkpoint_task}")
            else:
                to_task = f"transform__{to_name}"
                lines.append(f"    {from_task} >> {to_task}")

                # Add checkpoint if incremental
                if to_node.definition.mode.value == "incremental":
                    checkpoint_task = f"checkpoint__{to_name}"
                    lines.append(f"    {to_task} >> {checkpoint_task}")

        lines.append("")
        return lines


def refuse_placeholder_deploy(dag_code: str, allow: bool) -> Optional[str]:
    """Why this DAG must not be deployed, or None if it may be.

    The deploy endpoint wrote the DAG, unpaused it in Airflow, marked the pipeline
    "deployed" and returned 200 — for a DAG whose every task was an EmptyOperator.
    Each run then went green having moved no data, which is worse than a failure
    because the operator's own dashboard reports success.

    Deploying a skeleton to check the scheduling shape is a real thing to want. This
    only requires saying so.
    """
    pending = unimplemented_tasks(dag_code)
    if not pending or allow:
        return None
    return (f"This pipeline compiles to {len(pending)} placeholder task(s) that do "
            f"nothing: {', '.join(pending)}. Deploying it would produce successful "
            f"Airflow runs that move no data. Set "
            f"PIPELINES_ALLOW_PLACEHOLDER_DEPLOY=true to deploy it anyway.")
