"""Every domain module, merged.

Order is declaration order and nothing depends on it. A duplicate id is a programming
error, not a precedence question, so it raises here rather than letting one module
quietly win — tests/test_chat_analysis_assembly.py pins that.
"""
from typing import Callable, Dict, Tuple

from app.chat.actions import Action
from app.chat.analysis import (audit, catalog, connectors, dashboards, governance,
                               knowledge, pipelines, platform, query, spend)

_MODULES = (catalog, query, dashboards, knowledge, governance, spend, connectors,
            platform, pipelines, audit)

ACTIONS: Tuple[Action, ...] = tuple(a for m in _MODULES for a in m.ACTIONS)

_ids = [a.id for a in ACTIONS]
_dupes = sorted({i for i in _ids if _ids.count(i) > 1})
if _dupes:
    raise RuntimeError(f"duplicate action ids across analysis modules: {_dupes}")

EXECUTORS: Dict[str, Callable] = {k: v for m in _MODULES for k, v in m.EXECUTORS.items()}
RESOLVERS: Dict[str, Callable] = {k: v for m in _MODULES for k, v in m.RESOLVERS.items()}
PREVIEWERS: Dict[str, Callable] = {k: v for m in _MODULES for k, v in m.PREVIEWERS.items()}
