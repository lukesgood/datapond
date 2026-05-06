"""
Template engine for pipeline DSL.
Resolves template functions: {{ ref() }}, {{ source() }}, {{ incremental_filter() }}
"""
import re
from typing import List, Dict, Optional, Set
from jinja2 import Environment, BaseLoader, TemplateError


class PipelineTemplateEngine:
    """
    Jinja2-based template engine for pipeline SQL.
    Provides custom functions for table references and incremental logic.
    """

    def __init__(self):
        self.env = Environment(
            loader=BaseLoader(),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Register custom functions
        self.env.globals['ref'] = self._ref_placeholder
        self.env.globals['source'] = self._source_placeholder
        self.env.globals['streaming_source'] = self._streaming_source_placeholder
        self.env.globals['incremental_filter'] = self._incremental_filter_placeholder
        self.env.globals['current_timestamp'] = self._current_timestamp_placeholder

    @staticmethod
    def _ref_placeholder(table_name: str) -> str:
        """Placeholder for ref() - will be replaced during compilation"""
        return f"__REF__{table_name}__"

    @staticmethod
    def _source_placeholder(source_name: str) -> str:
        """Placeholder for source() - will be replaced during compilation"""
        return f"__SOURCE__{source_name}__"

    @staticmethod
    def _streaming_source_placeholder(source_name: str) -> str:
        """Placeholder for streaming_source()"""
        return f"__STREAMING_SOURCE__{source_name}__"

    @staticmethod
    def _incremental_filter_placeholder(column: Optional[str] = None) -> str:
        """Placeholder for incremental filter"""
        col = column or "updated_at"
        return f"__INCREMENTAL_FILTER__{col}__"

    @staticmethod
    def _current_timestamp_placeholder() -> str:
        """Placeholder for current timestamp"""
        return "__CURRENT_TIMESTAMP__"

    def extract_dependencies(self, sql: str) -> Set[str]:
        """
        Extract table/source dependencies from SQL template.
        Returns set of referenced table/source names.
        """
        dependencies = set()

        # Extract ref() calls
        ref_pattern = r'{{\s*ref\([\'"]([a-zA-Z0-9_]+)[\'"]\)\s*}}'
        for match in re.finditer(ref_pattern, sql):
            dependencies.add(match.group(1))

        # Extract source() calls
        source_pattern = r'{{\s*source\([\'"]([a-zA-Z0-9_]+)[\'"]\)\s*}}'
        for match in re.finditer(source_pattern, sql):
            dependencies.add(match.group(1))

        # Extract streaming_source() calls
        streaming_pattern = r'{{\s*streaming_source\([\'"]([a-zA-Z0-9_]+)[\'"]\)\s*}}'
        for match in re.finditer(streaming_pattern, sql):
            dependencies.add(match.group(1))

        return dependencies

    def render_template(self, sql: str) -> str:
        """
        Render SQL template with placeholders.
        Actual table names will be resolved by compiler.
        """
        try:
            template = self.env.from_string(sql)
            return template.render()
        except TemplateError as e:
            raise ValueError(f"Template rendering error: {e}")

    def resolve_ref(self, placeholder_sql: str, table_name: str, fqn: str) -> str:
        """Replace ref() placeholder with fully qualified table name"""
        placeholder = f"__REF__{table_name}__"
        return placeholder_sql.replace(placeholder, fqn)

    def resolve_source(self, placeholder_sql: str, source_name: str, fqn: str) -> str:
        """Replace source() placeholder with fully qualified table name"""
        placeholder = f"__SOURCE__{source_name}__"
        return placeholder_sql.replace(placeholder, fqn)

    def resolve_streaming_source(self, placeholder_sql: str, source_name: str, fqn: str) -> str:
        """Replace streaming_source() placeholder"""
        placeholder = f"__STREAMING_SOURCE__{source_name}__"
        return placeholder_sql.replace(placeholder, fqn)

    def resolve_incremental_filter(
        self,
        placeholder_sql: str,
        column: str,
        last_watermark: Optional[str] = None
    ) -> str:
        """
        Replace incremental_filter() placeholder with WHERE condition.

        Args:
            placeholder_sql: SQL with placeholders
            column: Watermark column name
            last_watermark: Last checkpoint value (None for first run)

        Returns:
            SQL with resolved WHERE clause
        """
        placeholder = f"__INCREMENTAL_FILTER__{column}__"

        if last_watermark is None:
            # First run: no filter
            where_clause = "1=1"
        else:
            # Incremental run: filter to new data
            where_clause = f"{column} > '{last_watermark}'"

        return placeholder_sql.replace(placeholder, where_clause)

    def resolve_current_timestamp(self, placeholder_sql: str, timestamp: str) -> str:
        """Replace current_timestamp() with actual timestamp"""
        placeholder = "__CURRENT_TIMESTAMP__"
        return placeholder_sql.replace(placeholder, f"TIMESTAMP '{timestamp}'")

    def resolve_all(
        self,
        sql: str,
        table_map: Dict[str, str],
        source_map: Dict[str, str],
        watermark_column: Optional[str] = None,
        last_watermark: Optional[str] = None,
        execution_timestamp: Optional[str] = None
    ) -> str:
        """
        Resolve all template placeholders in SQL.

        Args:
            sql: SQL with template placeholders
            table_map: Mapping of table names to FQNs
            source_map: Mapping of source names to FQNs
            watermark_column: Column for incremental filter
            last_watermark: Last checkpoint value
            execution_timestamp: Pipeline execution timestamp

        Returns:
            Fully resolved SQL
        """
        resolved = sql

        # Resolve refs
        for table_name, fqn in table_map.items():
            resolved = self.resolve_ref(resolved, table_name, fqn)

        # Resolve sources
        for source_name, fqn in source_map.items():
            resolved = self.resolve_source(resolved, source_name, fqn)
            resolved = self.resolve_streaming_source(resolved, source_name, fqn)

        # Resolve incremental filter
        if watermark_column and "__INCREMENTAL_FILTER__" in resolved:
            resolved = self.resolve_incremental_filter(
                resolved, watermark_column, last_watermark
            )

        # Resolve timestamp
        if execution_timestamp and "__CURRENT_TIMESTAMP__" in resolved:
            resolved = self.resolve_current_timestamp(resolved, execution_timestamp)

        return resolved


# Global template engine instance
template_engine = PipelineTemplateEngine()


def extract_sql_from_function(func) -> Optional[str]:
    """
    Extract SQL string from a function's return statement.
    Handles both single-line and multi-line SQL strings.
    """
    import inspect
    import ast

    try:
        source = inspect.getsource(func)
        tree = ast.parse(source)

        # Find function definition
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Look for return statement
                for stmt in node.body:
                    if isinstance(stmt, ast.Return) and stmt.value:
                        if isinstance(stmt.value, ast.Constant):
                            # Python 3.8+ uses ast.Constant
                            return stmt.value.value
                        elif isinstance(stmt.value, ast.Str):
                            # Python 3.7 uses ast.Str
                            return stmt.value.s

        return None
    except Exception:
        return None
