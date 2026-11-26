"""Run a Python source's code without giving it the backend.

The code used to run inside the backend process with a trimmed `__builtins__`. That
stops `open` and `import`, but not attribute walks such as
`().__class__.__base__.__subclasses__()`, which reach `os` from any object; and from the
backend process that means the database password, the key that decrypts every source's
credentials and the node's AWS role. A `while True: pass` also froze the backend, since
the code ran on the request loop with no time limit.

Two walls now:

1. `check(code)` reads the code's syntax tree before anything runs and refuses imports,
   any name or attribute starting with "_" (most escapes go through a dunder), the
   frame and code attributes that do not (`gi_frame`, `f_globals`, ...), and
   `str.format`/`format_map` (whose "{0.__class__}" fields walk attributes from inside a
   string). What is left is plain Python over the safe builtins in
   app/connectors/sandbox_runner.py.
2. `run(code)` executes it in a child process (`python -I`, empty environment) under a
   CPU-time and memory limit and a wall-clock timeout, off the request loop when called
   through `run_async`. A runaway is killed; the backend carries on.

The child runs as the same user in the same pod, so it is not a container boundary: it
is defence in depth behind the check, not a replacement for it. It also shares the
backend container's memory limit (1Gi on the reference install): a child allowed 1 GB,
or three children at once, would push the container over it and the kernel would kill
the backend, not just the child. So each child gets a small address-space limit, at
most CUSTOM_SOURCE_CONCURRENCY run at once (the rest wait their turn), and the child's
output goes to a file capped by RLIMIT_FSIZE instead of a pipe the backend would buffer
whole before measuring it.

Limits: CUSTOM_SOURCE_TIMEOUT_SECONDS (default 120), CUSTOM_SOURCE_MEMORY_MB (256),
CUSTOM_SOURCE_MAX_OUTPUT_MB (64), CUSTOM_SOURCE_CONCURRENCY (2). Raise the memory or
concurrency only together with the backend's memory limit.
"""
import ast
import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

RUNNER = str(Path(__file__).with_name("sandbox_runner.py"))
# str.format reads attributes from inside a string; the rest reach a frame or code
# object, whose f_globals/f_builtins hold the real modules and builtins.
_BANNED_ATTRS = {
    "format", "format_map", "mro",
    "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "cr_await", "ag_frame", "ag_code",
    "f_globals", "f_locals", "f_builtins", "f_back", "f_code", "tb_frame", "tb_next",
    "co_consts", "co_code", "with_traceback",
}


class SandboxError(Exception):
    """The code was refused, failed, or ran out of time or memory. `kind` is one of
    refused | syntax | error | timeout | memory | output."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def timeout_seconds() -> int:
    return _int_env("CUSTOM_SOURCE_TIMEOUT_SECONDS", 120)


def memory_mb() -> int:
    return _int_env("CUSTOM_SOURCE_MEMORY_MB", 256)


def max_output_bytes() -> int:
    return _int_env("CUSTOM_SOURCE_MAX_OUTPUT_MB", 64) * 1024 * 1024


_slots: Optional[threading.BoundedSemaphore] = None
_slots_lock = threading.Lock()


def _slot() -> threading.BoundedSemaphore:
    global _slots
    with _slots_lock:
        if _slots is None:
            _slots = threading.BoundedSemaphore(_int_env("CUSTOM_SOURCE_CONCURRENCY", 2))
        return _slots


def check(code: str) -> None:
    """Raise SandboxError(kind="refused"|"syntax") unless the code stays inside the
    allowed subset. Line numbers are named so the person can find it."""
    try:
        tree = ast.parse(code or "", filename="<custom_connector>")
    except SyntaxError as e:
        raise SandboxError(f"Syntax error in code: {e}", "syntax")
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SandboxError(f"Line {line}: imports are not allowed in a Python source. "
                               "Use only built-in Python (lists, dicts, loops, string formatting with %).",
                               "refused")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise SandboxError(f"Line {line}: attributes starting with '_' ({node.attr}) are not allowed.",
                                   "refused")
            if node.attr in ("format", "format_map"):
                raise SandboxError(f"Line {line}: str.{node.attr}() is not allowed; use % or f-strings.",
                                   "refused")
            if node.attr in _BANNED_ATTRS:
                raise SandboxError(f"Line {line}: the attribute {node.attr} is not allowed.", "refused")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            raise SandboxError(f"Line {line}: names starting with '__' ({node.id}) are not allowed.", "refused")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name.startswith("__"):
            raise SandboxError(f"Line {line}: names starting with '__' ({node.name}) are not allowed.", "refused")
        elif isinstance(node, ast.arg) and node.arg.startswith("__"):
            raise SandboxError(f"Line {line}: names starting with '__' ({node.arg}) are not allowed.", "refused")
        elif isinstance(node, (ast.Global, ast.Nonlocal)) and any(n.startswith("__") for n in node.names):
            raise SandboxError(f"Line {line}: names starting with '__' are not allowed.", "refused")


def run(code: str, mode: str = "fetch", timeout: Optional[int] = None) -> List[Dict[str, Any]]:
    """Check, then run in a child process. mode "define" only defines fetch_data (what
    Test connection does); "fetch" calls it and returns its records. Waits for a free
    slot first; the wait counts against the same timeout."""
    check(code)
    timeout = timeout or timeout_seconds()
    started = time.monotonic()
    slot = _slot()
    if not slot.acquire(timeout=timeout):
        raise SandboxError(f"Other Python sources were still running after {timeout} seconds; "
                           "try again when they finish.", "timeout")
    try:
        left = max(1, int(timeout - (time.monotonic() - started)))
        return _run_child(code, mode, left)
    finally:
        slot.release()


def _run_child(code: str, mode: str, timeout: int) -> List[Dict[str, Any]]:
    max_out = max_output_bytes()
    payload = json.dumps({"code": code, "mode": mode, "cpu_seconds": timeout,
                          "memory_mb": memory_mb(), "max_output_bytes": max_out})
    with tempfile.TemporaryFile() as out_file:
        try:
            proc = subprocess.run([sys.executable, "-I", RUNNER], input=payload.encode(), stdout=out_file,
                                  stderr=subprocess.DEVNULL, timeout=timeout,
                                  env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, cwd="/")
        except subprocess.TimeoutExpired:
            raise SandboxError(f"The code did not finish within {timeout} seconds and was stopped.", "timeout")
        size = out_file.tell()
        if proc.returncode == -signal.SIGXFSZ or size > max_out:
            raise SandboxError(f"fetch_data() returned more than {max_out // (1024 * 1024)} MB.", "output")
        out_file.seek(0)
        raw = out_file.read()
    try:
        out = json.loads(raw.decode() or "null")
    except ValueError:
        out = None
    if not isinstance(out, dict):
        # Killed by a limit (SIGXCPU / SIGKILL) or crashed before writing a result.
        if proc.returncode and proc.returncode < 0:
            raise SandboxError("The code was stopped: it used more CPU time or memory than allowed.", "memory")
        raise SandboxError("The code stopped without a result.", "error")
    if not out.get("ok"):
        raise SandboxError(out.get("error") or "The code failed.", out.get("kind") or "error")
    return out.get("records") or []


async def run_async(code: str, mode: str = "fetch", timeout: Optional[int] = None) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(run, code, mode, timeout)
