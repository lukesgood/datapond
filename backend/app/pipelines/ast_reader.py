"""Read a pipeline definition out of Python source without running it.

The compiler used to load a submitted pipeline file with `importlib` and call
`spec.loader.exec_module` on it. Everything at that file's top level then ran inside
the backend process, with the pod's filesystem, network and credentials — and the two
endpoints that did this, `/pipelines/validate` and `/pipelines/compile`, exist to
*describe* a pipeline, not to run one.

Nothing in the DSL needs to run to be described. `@pipeline`, `@source` and
`@live_table` take literal arguments, `@quality.*` takes two literal strings, and a
transform is a function whose body returns a SQL string — which the template engine
already read with `ast` rather than by calling it. So this module parses the file and
applies the real decorator functions to a stub, in the order Python would apply them.
The definitions, the pydantic validation and the error messages are therefore the same
ones the runtime DSL produces; only the execution is gone.

What this cannot do is describe a pipeline that is *computed* — tables built in a loop,
a name read from a variable, a schedule from an environment lookup. Those are reported
as errors naming the line, rather than quietly under-reporting the pipeline. A file
that needs to be executed to be understood is a file this product cannot validate
without executing it, and executing it is the thing being removed.
"""
import ast
from typing import Any, Callable, NamedTuple, Optional

from . import decorators as _decorators
from .decorators import get_pipeline_state
from .models import Pipeline


class PipelineSourceError(Exception):
    """The pipeline definition could not be read from the submitted source."""


# The decorators that declare something. Applied here exactly as Python applies them,
# so their signatures, defaults and validation stay the single source of truth.
_FACTORIES: dict[str, Callable[..., Any]] = {
    "pipeline": _decorators.pipeline,
    "source": _decorators.source,
    "live_table": _decorators.live_table,
}
_QUALITY_METHODS = ("expect", "expect_or_drop", "expect_or_fail")

_DSL_MODULE_SUFFIXES = ("pipelines", "pipelines.decorators", "decorators")


class ParsedPipeline(NamedTuple):
    pipeline: Pipeline
    notes: list[str]


def read_pipeline_source(source: str, filename: str = "pipeline.py") -> ParsedPipeline:
    """Parse `source` and return the pipeline it declares.

    Registers into `LiveTableRegistry` exactly as importing the file would have, so
    the caller resets the registry first the way it always did.

    Raises:
        PipelineSourceError: the source cannot be parsed, or declares something that
            can only be determined by running it.
        ValueError: no `@pipeline` was declared (from `get_pipeline_state`).
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        raise PipelineSourceError(
            f"Syntax error at line {e.lineno}: {e.msg}") from e

    aliases = _imported_names(tree)
    notes: list[str] = []
    unread = 0

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            notes.extend(_declare(node, aliases))
        elif isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef)):
            continue
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # module docstring, or a bare literal
        else:
            unread += 1

    if unread:
        notes.append(
            f"{unread} module-level statement(s) were read but not executed. A "
            f"pipeline definition is parsed, never run, so anything those statements "
            f"would have computed is not part of this pipeline.")

    return ParsedPipeline(get_pipeline_state(), notes)


def _declare(node: ast.FunctionDef | ast.AsyncFunctionDef,
             aliases: dict[str, str]) -> list[str]:
    """Apply the DSL decorators on one function definition. Returns any notes."""
    notes: list[str] = []
    obj: Any = _stub(node)

    # Bottom-up, the order Python applies decorators: @quality.* sits below
    # @live_table precisely so that live_table sees the checks it left behind.
    for decorator in reversed(node.decorator_list):
        where = f"line {decorator.lineno}"
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        parts = _dotted_name(target)
        factory = _resolve(parts, aliases)

        if factory is None:
            notes.append(
                f"'@{'.'.join(parts) if parts else '<expression>'}' on "
                f"'{node.name}' ({where}) is not a DataPond pipeline decorator and "
                f"was ignored; pipeline source is read, not executed.")
            continue

        if not isinstance(decorator, ast.Call):
            raise PipelineSourceError(
                f"@{'.'.join(parts)} at {where} must be called with arguments, "
                f"e.g. @{parts[-1]}(name=\"...\").")

        args, kwargs = _arguments(decorator, f"@{'.'.join(parts)} at {where}")
        try:
            obj = factory(*args, **kwargs)(obj)
        except Exception as e:
            raise PipelineSourceError(f"@{'.'.join(parts)} at {where}: {e}") from e

    table_def = getattr(obj, "_table_def", None)
    if table_def is not None:
        # The transform's SQL, read from its `return` — the same thing
        # `extract_sql_from_function` reads, minus the round trip through a live
        # function object we no longer have.
        sql = _returned_string(node)
        if sql is not None:
            table_def.transform_sql = sql

    return notes


def _stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Callable[..., Any]:
    """A stand-in for the decorated function: carries its name and docstring, and
    refuses to be called. The decorators want a function; nothing wants it run."""
    name = node.name
    doc = ast.get_docstring(node)

    def declared(*args, **kwargs):
        raise RuntimeError(
            f"'{name}' was read from pipeline source, not imported, and cannot be "
            f"called.")

    declared.__name__ = name
    declared.__qualname__ = name
    declared.__doc__ = doc
    return declared


def _returned_string(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[str]:
    """The string a transform returns, if its body is a plain `return "..."`."""
    for statement in node.body:
        if isinstance(statement, ast.Return) and isinstance(
                statement.value, ast.Constant) and isinstance(
                statement.value.value, str):
            return statement.value.value
    return None


def _imported_names(tree: ast.Module) -> dict[str, str]:
    """Local name -> DSL name, for `from app.pipelines import live_table as lt`."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if not node.module.endswith(_DSL_MODULE_SUFFIXES):
                continue
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    return aliases


def _dotted_name(node: ast.expr) -> Optional[list[str]]:
    """['quality', 'expect'] for `quality.expect`; None if it isn't a plain name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    parts.reverse()
    return parts


def _resolve(parts: Optional[list[str]],
             aliases: dict[str, str]) -> Optional[Callable[..., Any]]:
    """The DSL factory a decorator name refers to, or None if it isn't one."""
    if not parts:
        return None

    last = parts[-1]
    if len(parts) >= 2 and last in _QUALITY_METHODS:
        owner = aliases.get(parts[-2], parts[-2])
        if owner == "quality":
            return getattr(_decorators.quality, last)

    if len(parts) == 1:
        canonical = aliases.get(last, last)
        return _FACTORIES.get(canonical)

    # `dp.live_table(...)`, `app.pipelines.source(...)` — attribute access on a module.
    return _FACTORIES.get(last)


def _arguments(call: ast.Call, where: str) -> tuple[list[Any], dict[str, Any]]:
    """The decorator's arguments, which must all be literals.

    A non-literal argument is the one thing this reader will not guess at. Its value
    is whatever running the file would have produced, and running the file is the
    behaviour being removed — so it is reported, not assumed.
    """
    args = [_literal(a, where) for a in call.args]
    kwargs: dict[str, Any] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            raise PipelineSourceError(
                f"{where}: '**' argument unpacking cannot be read from source. "
                f"Write the arguments out.")
        kwargs[keyword.arg] = _literal(keyword.value, f"{where}, '{keyword.arg}'")
    return args, kwargs


def _literal(node: ast.expr, where: str) -> Any:
    if isinstance(node, ast.Starred):
        raise PipelineSourceError(
            f"{where}: '*' argument unpacking cannot be read from source. "
            f"Write the arguments out.")
    try:
        return ast.literal_eval(node)
    except Exception:
        raise PipelineSourceError(
            f"{where}: argument is not a literal value. A pipeline definition is "
            f"read, not executed, so its arguments have to be written out rather "
            f"than computed.") from None
