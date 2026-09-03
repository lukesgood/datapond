"""Late resolution of the function an executor reaches for.

Imported at call time, not at module import: the chat package must not pull the whole
API surface in just to declare what it can do. `test_chat_executor_wiring` calls every
resolver, so a renamed or moved target fails a test rather than a user's request.
"""


def _r(module: str, name: str):
    def _resolve():
        import importlib
        return getattr(importlib.import_module(module), name)
    return _resolve
