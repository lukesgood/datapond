"""
Dependency graph builder for pipeline tables.
Parses template references and constructs DAG for execution order.
"""
from typing import Dict, List, Set, Optional
from .models import (
    Pipeline,
    DependencyGraph,
    DependencyNode,
    TableDefinition,
    SourceDefinition
)
from .templates import template_engine, extract_sql_from_function


class PipelineValidationError(Exception):
    """Raised when pipeline validation fails"""
    pass


class DependencyGraphBuilder:
    """
    Builds dependency graph from pipeline definition.
    Validates references and detects circular dependencies.
    """

    @staticmethod
    def build_graph(pipeline: Pipeline) -> DependencyGraph:
        """
        Build dependency graph from pipeline definition.

        Args:
            pipeline: Pipeline with sources and tables

        Returns:
            DependencyGraph with all nodes and edges

        Raises:
            PipelineValidationError: If validation fails
        """
        graph = DependencyGraph()

        # Add source nodes (no dependencies)
        for source_name, source_def in pipeline.sources.items():
            graph.add_node(source_name, "source", source_def)

        # Add table nodes and extract dependencies
        for table_name, table_def in pipeline.tables.items():
            graph.add_node(table_name, "table", table_def)

            # Extract SQL from transform function
            sql = extract_sql_from_function(table_def.transform_fn)
            if sql:
                # Parse template dependencies
                dependencies = template_engine.extract_dependencies(sql)
                table_def.dependencies = list(dependencies)
                table_def.transform_sql = sql
            else:
                # Python transform - assume no SQL dependencies for now
                # Could be enhanced to parse context.read_table() calls
                pass

        # Build edges from dependencies
        for table_name, table_def in pipeline.tables.items():
            for dep_name in table_def.dependencies:
                if dep_name not in graph.nodes:
                    raise PipelineValidationError(
                        f"Table '{table_name}' references unknown table/source '{dep_name}'"
                    )
                graph.add_edge(dep_name, table_name)

        return graph

    @staticmethod
    def validate_graph(graph: DependencyGraph) -> List[str]:
        """
        Validate dependency graph.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check for cycles
        if graph.has_cycle():
            errors.append("Circular dependency detected in pipeline")

            # Try to identify the cycle
            cycle = DependencyGraphBuilder._find_cycle(graph)
            if cycle:
                cycle_str = " -> ".join(cycle + [cycle[0]])
                errors.append(f"Cycle path: {cycle_str}")

        # Check for orphaned nodes (no dependencies and no dependents)
        for node_name, node in graph.nodes.items():
            if node.type == "table" and not node.dependencies and not node.dependents:
                errors.append(
                    f"Table '{node_name}' has no dependencies and no dependents (orphaned)"
                )

        return errors

    @staticmethod
    def _find_cycle(graph: DependencyGraph) -> Optional[List[str]]:
        """Find a cycle in the graph using DFS"""
        visited = set()
        rec_stack = []

        def dfs(node: str, path: List[str]) -> Optional[List[str]]:
            visited.add(node)
            path.append(node)

            for dependent in graph.nodes[node].dependents:
                if dependent not in visited:
                    result = dfs(dependent, path.copy())
                    if result:
                        return result
                elif dependent in path:
                    # Found cycle
                    cycle_start = path.index(dependent)
                    return path[cycle_start:]

            return None

        for node in graph.nodes:
            if node not in visited:
                result = dfs(node, [])
                if result:
                    return result

        return None

    @staticmethod
    def get_execution_order(graph: DependencyGraph) -> List[List[str]]:
        """
        Get execution order as list of batches.
        Tables in the same batch can run in parallel.

        Returns:
            List of batches, where each batch is a list of table names
        """
        try:
            sorted_nodes = graph.topological_sort()
        except ValueError as e:
            raise PipelineValidationError(f"Cannot determine execution order: {e}")

        # Group into batches by depth (level in DAG)
        node_levels = {}

        def compute_level(node_name: str) -> int:
            if node_name in node_levels:
                return node_levels[node_name]

            node = graph.nodes[node_name]
            if not node.dependencies:
                # Source or table with no deps: level 0
                level = 0
            else:
                # Level is max(dependency levels) + 1
                level = max(compute_level(dep) for dep in node.dependencies) + 1

            node_levels[node_name] = level
            return level

        # Compute levels for all nodes
        for node_name in sorted_nodes:
            compute_level(node_name)

        # Group by level
        max_level = max(node_levels.values()) if node_levels else 0
        batches = [[] for _ in range(max_level + 1)]

        for node_name, level in node_levels.items():
            batches[level].append(node_name)

        # Filter out empty batches and source-only batches
        # (sources don't need execution, they're just ingested)
        result_batches = []
        for batch in batches:
            table_batch = [
                name for name in batch
                if graph.nodes[name].type == "table"
            ]
            if table_batch:
                result_batches.append(table_batch)

        return result_batches

    @staticmethod
    def get_table_lineage(graph: DependencyGraph, table_name: str) -> Dict[str, any]:
        """
        Get lineage information for a specific table.

        Returns:
            Dict with upstream and downstream tables
        """
        if table_name not in graph.nodes:
            raise ValueError(f"Table '{table_name}' not found in graph")

        node = graph.nodes[table_name]

        # Get all upstream dependencies (recursive)
        upstream = set()

        def traverse_upstream(name: str):
            for dep in graph.nodes[name].dependencies:
                if dep not in upstream:
                    upstream.add(dep)
                    traverse_upstream(dep)

        traverse_upstream(table_name)

        # Get all downstream dependents (recursive)
        downstream = set()

        def traverse_downstream(name: str):
            for dep in graph.nodes[name].dependents:
                if dep not in downstream:
                    downstream.add(dep)
                    traverse_downstream(dep)

        traverse_downstream(table_name)

        return {
            "table": table_name,
            "type": node.type,
            "direct_dependencies": node.dependencies,
            "direct_dependents": node.dependents,
            "all_upstream": list(upstream),
            "all_downstream": list(downstream)
        }

    @staticmethod
    def visualize_graph(graph: DependencyGraph) -> str:
        """
        Generate ASCII visualization of dependency graph.

        Returns:
            Multi-line string with graph visualization
        """
        lines = []
        lines.append("Pipeline Dependency Graph")
        lines.append("=" * 50)

        # Get execution batches
        batches = DependencyGraphBuilder.get_execution_order(graph)

        for i, batch in enumerate(batches):
            lines.append(f"\nBatch {i + 1} (parallel execution):")
            for table_name in batch:
                node = graph.nodes[table_name]
                deps_str = ", ".join(node.dependencies) if node.dependencies else "none"
                lines.append(f"  - {table_name} (depends on: {deps_str})")

        # Add edge list
        lines.append("\nEdges (dependencies):")
        for from_name, to_name in graph.edges:
            lines.append(f"  {from_name} → {to_name}")

        return "\n".join(lines)
