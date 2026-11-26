"""Runs one Python source's code in a child process. Standard library only: it is
started as `python -I <this file>` with an empty environment, so it cannot import the
application and the application's secrets are not in its environment.

Reads {"code": str, "mode": "define" | "fetch"} as JSON on stdin and writes one JSON
object to stdout: {"ok": true, "records": [...]} (fetch), {"ok": true} (define), or
{"ok": false, "error": str, "kind": str}.

The code was checked by app/connectors/sandbox.py before it got here (no imports, no
names or attributes starting with "_", no str.format); this process is the second
wall: limits on CPU time and memory, no secrets to read, and its death does not take
the backend with it.
"""
import json
import sys

SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "bytes", "chr", "dict", "divmod", "enumerate", "filter",
    "float", "frozenset", "hasattr", "hash", "hex", "int", "isinstance", "iter", "len",
    "list", "map", "max", "min", "next", "oct", "ord", "pow", "range", "repr", "reversed",
    "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
    "ValueError", "TypeError", "KeyError", "IndexError", "Exception", "RuntimeError",
    "NotImplementedError", "ZeroDivisionError", "StopIteration",
)


def _limits(cpu_seconds: int, memory_mb: int, max_output_bytes: int) -> None:
    import resource
    for which, value in ((resource.RLIMIT_CPU, cpu_seconds),
                         (resource.RLIMIT_AS, memory_mb * 1024 * 1024),
                         # stdout is a file: a result larger than this stops the child
                         # (SIGXFSZ) instead of filling the backend's memory.
                         (resource.RLIMIT_FSIZE, max_output_bytes + 1),
                         (resource.RLIMIT_NOFILE, 16)):
        try:
            resource.setrlimit(which, (value, value))
        except (ValueError, OSError):   # not every platform allows every limit
            pass


def main() -> int:
    req = json.loads(sys.stdin.read() or "{}")
    _limits(int(req.get("cpu_seconds") or 120), int(req.get("memory_mb") or 256),
            int(req.get("max_output_bytes") or 64 * 1024 * 1024))
    import builtins
    safe = {n: getattr(builtins, n) for n in SAFE_BUILTIN_NAMES}
    namespace = {"__builtins__": safe, "__name__": "__datapond_custom__", "__doc__": None}
    out = sys.stdout
    try:
        exec(compile(req["code"], "<custom_connector>", "exec"), namespace)  # noqa: S102
        fetch = namespace.get("fetch_data")
        if fetch is None or not callable(fetch):
            raise ValueError("fetch_data() function not found. "
                             "Your code must define: def fetch_data() -> list[dict]: ...")
        if req.get("mode") == "define":
            out.write(json.dumps({"ok": True}))
            return 0
        records = fetch()
        if not isinstance(records, list):
            raise ValueError(f"fetch_data() must return a list of dicts, got {type(records).__name__}")
        out.write(json.dumps({"ok": True, "records": records}, default=str, ensure_ascii=False))
        return 0
    except MemoryError:
        out.write(json.dumps({"ok": False, "kind": "memory", "error": "The code ran out of memory."}))
    except SyntaxError as e:
        out.write(json.dumps({"ok": False, "kind": "syntax", "error": f"Syntax error in code: {e}"}))
    except Exception as e:
        out.write(json.dumps({"ok": False, "kind": "error", "error": f"{type(e).__name__}: {e}"}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
