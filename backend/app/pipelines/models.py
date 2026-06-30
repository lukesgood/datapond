"""
Pydantic models for declarative pipeline framework.
Represents pipeline definitions, tables, sources, and quality checks.
"""
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any, Callable, Literal
from enum import Enum
from datetime import datetime
import uuid


class ProcessingMode(str, Enum):
    """Table processing mode"""
    FULL_REFRESH = "full_refresh"
    INCREMENTAL = "incremental"
    STREAMING = "streaming"


class QualityAction(str, Enum):
    """Quality check action on violation"""
    LOG = "log"  # @expect - log warning, continue
    DROP = "drop"  # @expect_or_drop - filter bad rows
    FAIL = "fail"  # @expect_or_fail - fail pipeline


class Engine(str, Enum):
    """Execution engine for transforms"""
    TRINO = "trino"
    SPARK = "spark"
    PYTHON = "python"
    RISINGWAVE = "risingwave"
    DUCKDB = "duckdb"


class QualityCheck(BaseModel):
    """Data quality constraint"""
    name: str = Field(..., description="Check name (unique within table)")
    condition: str = Field(..., description="SQL WHERE condition (must evaluate to boolean)")
    action: QualityAction = Field(..., description="Action on violation")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure valid check name"""
        if not v or not v.replace("_", "").isalnum():
            raise ValueError("Check name must be alphanumeric with underscores")
        return v

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, v: str) -> str:
        """Basic SQL injection prevention"""
        dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER", "CREATE", "INSERT", "UPDATE"]
        upper_sql = v.upper()
        for keyword in dangerous_keywords:
            if keyword in upper_sql:
                raise ValueError(f"Dangerous SQL keyword '{keyword}' not allowed in quality checks")
        return v


class SourceDefinition(BaseModel):
    """External data source definition"""
    name: str = Field(..., description="Source name (unique within pipeline)")
    source_type: str = Field(..., description="Source type (postgres, mysql, kafka, etc.)")
    connection_id: str = Field(..., description="Airflow connection ID")
    table: Optional[str] = Field(None, description="Source table name (for DB sources)")
    topic: Optional[str] = Field(None, description="Kafka topic name (for streaming sources)")
    mode: ProcessingMode = Field(ProcessingMode.FULL_REFRESH, description="Processing mode")
    watermark_column: Optional[str] = Field(None, description="Column for incremental detection")
    catalog: str = Field("datapond", description="Target catalog")
    namespace: str = Field("bronze", description="Target namespace")
    schema: Optional[Dict[str, str]] = Field(None, description="Schema definition (for streaming)")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Additional properties")

    # Internal metadata
    source_fn: Optional[Callable] = Field(None, exclude=True, description="Decorated function reference")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure valid source name"""
        if not v or not v.replace("_", "").isalnum():
            raise ValueError("Source name must be alphanumeric with underscores")
        return v

    def get_fqn(self) -> str:
        """Get fully qualified name"""
        return f"{self.catalog}.{self.namespace}.{self.name}"


class TableDefinition(BaseModel):
    """Live table definition (@live_table)"""
    name: str = Field(..., description="Table name (unique within pipeline)")
    comment: str = Field("", description="Table description")
    catalog: str = Field("datapond", description="Iceberg catalog")
    namespace: str = Field("silver", description="Iceberg namespace (bronze/silver/gold)")
    mode: ProcessingMode = Field(ProcessingMode.FULL_REFRESH, description="Processing mode")
    partition_by: List[str] = Field(default_factory=list, description="Partition columns")
    engine: Engine = Field(Engine.TRINO, description="Execution engine")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Iceberg table properties")

    # Transform definition
    transform_fn: Optional[Callable] = Field(None, exclude=True, description="Transform function")
    transform_sql: Optional[str] = Field(None, description="SQL transform (extracted from function)")

    # Quality checks
    quality_checks: List[QualityCheck] = Field(default_factory=list, description="Data quality constraints")

    # Dependencies (extracted from templates)
    dependencies: List[str] = Field(default_factory=list, description="Referenced table/source names")

    # Incremental state
    watermark_column: Optional[str] = Field(None, description="Column for incremental processing")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure valid table name"""
        if not v or not v.replace("_", "").isalnum():
            raise ValueError("Table name must be alphanumeric with underscores")
        return v

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        """Validate namespace"""
        valid_namespaces = ["bronze", "silver", "gold", "streaming"]
        if v not in valid_namespaces:
            raise ValueError(f"Namespace must be one of {valid_namespaces}")
        return v

    def get_fqn(self) -> str:
        """Get fully qualified name"""
        return f"{self.catalog}.{self.namespace}.{self.name}"

    def add_quality_check(self, check: QualityCheck):
        """Add a quality check"""
        # Ensure unique check names
        existing_names = {c.name for c in self.quality_checks}
        if check.name in existing_names:
            raise ValueError(f"Quality check '{check.name}' already exists")
        self.quality_checks.append(check)


class PipelineDefinition(BaseModel):
    """Pipeline metadata"""
    name: str = Field(..., description="Pipeline name (unique globally)")
    schedule: str = Field("@daily", description="Cron schedule or Airflow preset")
    tags: List[str] = Field(default_factory=list, description="Tags for organization")
    owner: str = Field("data-team@datapond.io", description="Pipeline owner email")
    max_retries: int = Field(2, description="Max retries on failure")
    retry_delay_minutes: int = Field(5, description="Delay between retries")
    alert_on_failure: bool = Field(True, description="Send alerts on failure")
    alert_email: Optional[str] = Field(None, description="Email address(es) for failure alerts, comma-separated")
    alert_channel: Optional[str] = Field(None, description="Alert channel (reserved for future use)")
    description: Optional[str] = Field(None, description="Pipeline description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure valid pipeline name"""
        if not v or not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Pipeline name must be alphanumeric with underscores/hyphens")
        return v

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, v: str) -> str:
        """Basic cron/preset validation"""
        presets = ["@once", "@hourly", "@daily", "@weekly", "@monthly", "@yearly"]
        if v in presets:
            return v
        # Basic cron validation (5 or 6 fields)
        parts = v.split()
        if len(parts) not in [5, 6]:
            raise ValueError("Schedule must be Airflow preset or valid cron expression")
        return v


class Pipeline(BaseModel):
    """Complete pipeline with all definitions"""
    pipeline: PipelineDefinition = Field(..., description="Pipeline metadata")
    sources: Dict[str, SourceDefinition] = Field(default_factory=dict, description="Source definitions")
    tables: Dict[str, TableDefinition] = Field(default_factory=dict, description="Table definitions")

    # Compilation metadata
    compiled_at: Optional[datetime] = Field(None, description="Compilation timestamp")
    compiler_version: str = Field("0.1.0", description="Compiler version")

    def get_all_table_names(self) -> List[str]:
        """Get all table and source names"""
        return list(self.sources.keys()) + list(self.tables.keys())

    def get_table_or_source(self, name: str) -> Optional[TableDefinition | SourceDefinition]:
        """Get table or source by name"""
        return self.tables.get(name) or self.sources.get(name)

    def validate_references(self):
        """Validate all table references exist"""
        all_names = set(self.get_all_table_names())
        for table in self.tables.values():
            for dep in table.dependencies:
                if dep not in all_names:
                    raise ValueError(
                        f"Table '{table.name}' references unknown table/source '{dep}'"
                    )


class DependencyNode(BaseModel):
    """Node in dependency graph"""
    model_config = {"arbitrary_types_allowed": True}

    name: str
    type: Literal["source", "table"]
    definition: Any = Field(..., description="TableDefinition or SourceDefinition")
    dependencies: List[str] = Field(default_factory=list)
    dependents: List[str] = Field(default_factory=list)


class DependencyGraph(BaseModel):
    """Directed acyclic graph of table dependencies"""
    nodes: Dict[str, DependencyNode] = Field(default_factory=dict)
    edges: List[tuple[str, str]] = Field(default_factory=list)

    def add_node(self, name: str, node_type: Literal["source", "table"],
                 definition: TableDefinition | SourceDefinition):
        """Add node to graph"""
        self.nodes[name] = DependencyNode(
            name=name,
            type=node_type,
            definition=definition,
            dependencies=[],
            dependents=[]
        )

    def add_edge(self, from_name: str, to_name: str):
        """Add dependency edge (from -> to means 'to' depends on 'from')"""
        if from_name not in self.nodes or to_name not in self.nodes:
            raise ValueError(f"Cannot add edge: node not found")

        self.edges.append((from_name, to_name))
        self.nodes[from_name].dependents.append(to_name)
        self.nodes[to_name].dependencies.append(from_name)

    def has_cycle(self) -> bool:
        """Check for circular dependencies using DFS"""
        visited = set()
        rec_stack = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for dependent in self.nodes[node].dependents:
                if dependent not in visited:
                    if dfs(dependent):
                        return True
                elif dependent in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in self.nodes:
            if node not in visited:
                if dfs(node):
                    return True
        return False

    def topological_sort(self) -> List[str]:
        """Return nodes in topological order (execution order)"""
        in_degree = {name: len(node.dependencies) for name, node in self.nodes.items()}
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            for dependent in self.nodes[node].dependents:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self.nodes):
            raise ValueError("Circular dependency detected in topological sort")

        return result


class CompilationResult(BaseModel):
    """Result of pipeline compilation"""
    pipeline_name: str
    artifacts: List[tuple[str, str]] = Field(default_factory=list)  # (type, content)
    dependency_graph: Optional[DependencyGraph] = None
    validation_errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    compiled_at: datetime = Field(default_factory=datetime.utcnow)
    success: bool = True

    def add_artifact(self, artifact_type: str, content: str):
        """Add compilation artifact"""
        self.artifacts.append((artifact_type, content))

    def add_error(self, error: str):
        """Add validation error"""
        self.validation_errors.append(error)
        self.success = False

    def add_warning(self, warning: str):
        """Add warning"""
        self.warnings.append(warning)
