"""Every call to register_lineage passes only arguments it takes.

The streamed sync called it with source_name/source_schema/target_table/... long after
its signature became (source_fqn, target_fqn, connector_name). The TypeError surfaced
after the success history row, so each console sync also recorded a "failed" run and
skipped the RAG nudge.
"""
import ast
import inspect
from pathlib import Path

from app.api import connectors

SRC = Path(connectors.__file__)


def _calls(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == name:
            yield node


def test_register_lineage_keywords_match_signature():
    params = set(inspect.signature(connectors.register_lineage).parameters)
    calls = list(_calls(ast.parse(SRC.read_text()), "register_lineage"))
    assert calls, "expected at least one call"
    for call in calls:
        kws = {k.arg for k in call.keywords}
        assert kws <= params, f"line {call.lineno}: {sorted(kws - params)}"


def test_stream_and_sync_share_om_reflection():
    tree = ast.parse(SRC.read_text())
    callers = {f.name for f in ast.walk(tree) if isinstance(f, ast.AsyncFunctionDef)
               and any(True for _ in _calls(f, "_reflect_tables_in_om"))}
    assert {"sync_stream", "_persist_sync_session"} <= callers
