"""
Decorators for declarative pipeline DSL.
Provides @pipeline, @source, @live_table, and @quality decorators.
"""
from typing import Callable, Optional, List, Dict, Any
from functools import wraps
import inspect

from .models import (
    PipelineDefinition,
    SourceDefinition,
    TableDefinition,
    QualityCheck,
    ProcessingMode,
    Engine,
    QualityAction
)


class LiveTableRegistry:
    """
    Global registry for decorated pipeline components.
    Stores pipeline metadata, sources, and tables defined via decorators.
    """
    _instance: Optional['LiveTableRegistry'] = None
    _pipeline: Optional[PipelineDefinition] = None
    _sources: Dict[str, SourceDefinition] = {}
    _tables: Dict[str, TableDefinition] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset registry (useful for testing)"""
        cls._pipeline = None
        cls._sources = {}
        cls._tables = {}

    @classmethod
    def set_pipeline(cls, pipeline_def: PipelineDefinition):
        """Register pipeline metadata"""
        if cls._pipeline is not None:
            raise ValueError(f"Pipeline already defined: {cls._pipeline.name}")
        cls._pipeline = pipeline_def

    @classmethod
    def register_source(cls, source_def: SourceDefinition):
        """Register a source"""
        if source_def.name in cls._sources:
            raise ValueError(f"Source '{source_def.name}' already registered")
        cls._sources[source_def.name] = source_def

    @classmethod
    def register_table(cls, table_def: TableDefinition):
        """Register a table"""
        if table_def.name in cls._tables:
            raise ValueError(f"Table '{table_def.name}' already registered")
        cls._tables[table_def.name] = table_def

    @classmethod
    def get_pipeline(cls) -> Optional[PipelineDefinition]:
        """Get pipeline metadata"""
        return cls._pipeline

    @classmethod
    def get_sources(cls) -> Dict[str, SourceDefinition]:
        """Get all sources"""
        return cls._sources.copy()

    @classmethod
    def get_tables(cls) -> Dict[str, TableDefinition]:
        """Get all tables"""
        return cls._tables.copy()

    @classmethod
    def get_source(cls, name: str) -> Optional[SourceDefinition]:
        """Get source by name"""
        return cls._sources.get(name)

    @classmethod
    def get_table(cls, name: str) -> Optional[TableDefinition]:
        """Get table by name"""
        return cls._tables.get(name)


# Global registry instance
registry = LiveTableRegistry()


def pipeline(
    name: str,
    schedule: str = "@daily",
    tags: Optional[List[str]] = None,
    owner: str = "data-team@datapond.io",
    max_retries: int = 2,
    retry_delay_minutes: int = 5,
    alert_on_failure: bool = True,
    alert_email: Optional[str] = None,
    alert_channel: Optional[str] = None,
    description: Optional[str] = None
):
    """
    Decorator to define pipeline metadata.
    Must be used once at the top of the pipeline file.

    Example:
        @pipeline(
            name="ecommerce_analytics",
            schedule="@hourly",
            tags=["ecommerce", "analytics"],
            owner="analytics@company.com"
        )
    """
    def decorator(func: Callable) -> Callable:
        pipeline_def = PipelineDefinition(
            name=name,
            schedule=schedule,
            tags=tags or [],
            owner=owner,
            max_retries=max_retries,
            retry_delay_minutes=retry_delay_minutes,
            alert_on_failure=alert_on_failure,
            alert_email=alert_email,
            alert_channel=alert_channel,
            description=description or inspect.getdoc(func)
        )
        LiveTableRegistry.set_pipeline(pipeline_def)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def source(
    name: str,
    connection: Optional[str] = None,  # Alias for connection_id
    connection_id: Optional[str] = None,
    source_type: str = "postgres",
    table: Optional[str] = None,
    topic: Optional[str] = None,
    mode: str = "full_refresh",
    watermark_column: Optional[str] = None,
    catalog: str = "datapond",
    namespace: str = "bronze",
    schema: Optional[Dict[str, str]] = None,
    **properties
):
    """
    Decorator to define an external data source.

    Example:
        @source(
            name="raw_orders",
            connection="postgres_oltp",
            table="public.orders",
            mode="incremental",
            watermark_column="updated_at"
        )
        def raw_orders_source():
            pass
    """
    def decorator(func: Callable) -> Callable:
        # Handle connection alias (treat empty string as missing)
        conn_id = (connection_id or connection or "").strip() or None
        if not conn_id:
            raise ValueError(f"Source '{name}': 'connection' 파라미터가 필요합니다. 커넥터를 먼저 선택하세요.")

        source_def = SourceDefinition(
            name=name,
            source_type=source_type,
            connection_id=conn_id,
            table=table,
            topic=topic,
            mode=ProcessingMode(mode),
            watermark_column=watermark_column,
            catalog=catalog,
            namespace=namespace,
            schema=schema,
            properties=properties,
            source_fn=func
        )
        LiveTableRegistry.register_source(source_def)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def live_table(
    name: str,
    comment: str = "",
    catalog: str = "datapond",
    namespace: str = "silver",
    mode: str = "full_refresh",
    partition_by: Optional[List[str]] = None,
    engine: str = "trino",
    watermark_column: Optional[str] = None,
    **properties
):
    """
    Decorator to define a live table (transformation).

    The decorated function should return:
    - SQL string (for SQL-based transforms)
    - Pandas DataFrame (for Python transforms)

    Example:
        @live_table(
            name="clean_orders",
            comment="Cleaned orders with validation",
            mode="incremental",
            partition_by=["order_date"]
        )
        def clean_orders():
            return '''
                SELECT * FROM {{ source('raw_orders') }}
                WHERE {{ incremental_filter('updated_at') }}
            '''
    """
    def decorator(func: Callable) -> Callable:
        # Extract SQL from function if it returns a string
        transform_sql = None
        if inspect.getsource(func):
            # Function body will be parsed later by compiler
            pass

        table_def = TableDefinition(
            name=name,
            comment=comment or inspect.getdoc(func) or "",
            catalog=catalog,
            namespace=namespace,
            mode=ProcessingMode(mode),
            partition_by=partition_by or [],
            engine=Engine(engine),
            watermark_column=watermark_column,
            properties=properties,
            transform_fn=func,
            transform_sql=transform_sql
        )

        # Apply pending quality checks (if any)
        if hasattr(func, '_pending_quality_checks'):
            for check in func._pending_quality_checks:
                table_def.add_quality_check(check)

        LiveTableRegistry.register_table(table_def)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Store table definition on function for reference
        wrapper._table_def = table_def
        return wrapper

    return decorator


class quality:
    """
    Namespace for quality check decorators.
    Must be applied BELOW @live_table decorator (decorators run bottom-up).
    """

    @staticmethod
    def expect(name: str, condition: str):
        """
        Log violations but continue execution.

        Example:
            @live_table(name="x")
            @quality.expect("valid_amount", "amount > 0")
            def func(): ...
        """
        def decorator(func: Callable) -> Callable:
            # Store quality check for later application
            check = QualityCheck(
                name=name,
                condition=condition,
                action=QualityAction.LOG
            )

            # Add to pending checks
            if not hasattr(func, '_pending_quality_checks'):
                func._pending_quality_checks = []
            func._pending_quality_checks.append(check)

            return func

        return decorator

    @staticmethod
    def expect_or_drop(name: str, condition: str):
        """
        Filter out rows that violate the condition.

        Example:
            @live_table(name="x")
            @quality.expect_or_drop("valid_status", "status IN ('active', 'pending')")
            def func(): ...
        """
        def decorator(func: Callable) -> Callable:
            # Store quality check for later application
            check = QualityCheck(
                name=name,
                condition=condition,
                action=QualityAction.DROP
            )

            # Add to pending checks
            if not hasattr(func, '_pending_quality_checks'):
                func._pending_quality_checks = []
            func._pending_quality_checks.append(check)

            return func

        return decorator

    @staticmethod
    def expect_or_fail(name: str, condition: str):
        """
        Fail pipeline if condition is violated.

        Example:
            @live_table(name="x")
            @quality.expect_or_fail("non_null_id", "order_id IS NOT NULL")
            def func(): ...
        """
        def decorator(func: Callable) -> Callable:
            # Store quality check for later application
            check = QualityCheck(
                name=name,
                condition=condition,
                action=QualityAction.FAIL
            )

            # Add to pending checks
            if not hasattr(func, '_pending_quality_checks'):
                func._pending_quality_checks = []
            func._pending_quality_checks.append(check)

            return func

        return decorator


# Convenience function to get current pipeline state
def get_pipeline_state():
    """Get current pipeline definition from registry"""
    from .models import Pipeline

    pipeline_def = LiveTableRegistry.get_pipeline()
    if not pipeline_def:
        raise ValueError("No pipeline defined. Use @pipeline decorator.")

    return Pipeline(
        pipeline=pipeline_def,
        sources=LiveTableRegistry.get_sources(),
        tables=LiveTableRegistry.get_tables()
    )
