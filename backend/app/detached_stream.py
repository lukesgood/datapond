"""Run an SSE generator to the end whether or not anyone is still listening.

A StreamingResponse cancels its generator when the client goes away (tab closed, proxy
idle timeout, pod-to-browser network drop). For a sync that means the run stops between
tables and its history row is never written — the page that reconnects finds nothing.
Here the generator runs in its own task and feeds a queue; the response only reads the
queue. If the reader is cancelled, the task keeps going and records its outcome.

While the work is quiet (one large table can take minutes) a comment line goes out every
`keepalive` seconds so idle proxies do not close the stream.
"""
import asyncio
from typing import AsyncIterator, Set

_RUNNING: Set[asyncio.Task] = set()   # strong refs: a bare task can be garbage-collected
_END = object()


def detach(gen: AsyncIterator[str], keepalive: float = 15.0) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue()

    async def pump():
        try:
            async for item in gen:
                queue.put_nowait(item)
        finally:
            queue.put_nowait(_END)

    task = asyncio.create_task(pump())
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)

    async def read() -> AsyncIterator[str]:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=keepalive)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if item is _END:
                if task.done() and not task.cancelled() and task.exception():
                    raise task.exception()
                return
            yield item

    return read()
