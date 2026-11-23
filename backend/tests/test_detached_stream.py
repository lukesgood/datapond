import asyncio

from app.detached_stream import detach


def test_passes_items_through_in_order():
    async def gen():
        for i in range(3):
            yield f"e{i}"

    async def main():
        return [x async for x in detach(gen())]

    assert asyncio.run(main()) == ["e0", "e1", "e2"]


def test_work_finishes_after_the_reader_goes_away():
    done = []

    async def gen():
        yield "start"
        await asyncio.sleep(0.05)
        yield "middle"
        done.append("recorded")   # e.g. the history row

    async def main():
        stream = detach(gen())
        assert await stream.__anext__() == "start"
        await stream.aclose()      # client disconnected
        await asyncio.sleep(0.1)

    asyncio.run(main())
    assert done == ["recorded"]


def test_keepalive_while_quiet():
    async def gen():
        await asyncio.sleep(0.05)
        yield "late"

    async def main():
        return [x async for x in detach(gen(), keepalive=0.01)]

    out = asyncio.run(main())
    assert out[-1] == "late" and out[0] == ": keepalive\n\n"


def test_generator_error_reaches_the_reader():
    async def gen():
        yield "a"
        raise RuntimeError("boom")

    async def main():
        got = []
        try:
            async for x in detach(gen()):
                got.append(x)
        except RuntimeError as e:
            got.append(str(e))
        return got

    assert asyncio.run(main()) == ["a", "boom"]
