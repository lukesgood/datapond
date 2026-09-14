"""spend_summary against the gateway's real /key/list contract.

LiteLLM refuses `size` above 100 with 422 ("Input should be less than or equal to 100")
and `page` below 1. spend_summary asked for size=500, so on the live deployment every
call came back 422 and was reported as `unavailable` — which the AI Gateway page then
crashed on. The fake below enforces that contract instead of answering whatever it is
asked, so a request the real gateway would refuse fails here as well.
"""
import asyncio


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class _Gateway:
    """Pages `keys` the way LiteLLM's /key/list does, and refuses what it refuses."""

    MAX_SIZE = 100

    def __init__(self, keys, fail_on_page=None):
        self.keys = keys
        self.fail_on_page = fail_on_page
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        params = dict(params or {})
        self.requests.append(params)
        size = int(params.get("size", 10))
        page = int(params.get("page", 1))
        if size > self.MAX_SIZE:
            return _Resp(422, {"detail": [{"msg": "Input should be less than or equal to 100"}]})
        if page < 1:
            return _Resp(422, {"detail": [{"msg": "Input should be greater than or equal to 1"}]})
        if page == self.fail_on_page:
            return _Resp(500, {"detail": "boom"})
        start = (page - 1) * size
        # LiteLLM reports total_pages 0, not 1, when there are no keys.
        total_pages = -(-len(self.keys) // size)
        return _Resp(200, {"keys": self.keys[start:start + size], "total_count": len(self.keys),
                           "current_page": page, "total_pages": total_pages})


def _install(monkeypatch, gateway):
    from app.api import ai_backends
    monkeypatch.setattr(ai_backends, "_gateway", lambda: ("http://gw", "sk-test"))
    monkeypatch.setattr(ai_backends.httpx, "AsyncClient", lambda *a, **k: gateway)


def _summary():
    from app.api.ai_backends import spend_summary
    return asyncio.run(spend_summary())


def test_it_only_asks_for_pages_the_gateway_accepts(monkeypatch):
    gw = _Gateway([{"spend": 1.0}])
    _install(monkeypatch, gw)
    out = _summary()
    assert all(int(p.get("size", 10)) <= _Gateway.MAX_SIZE for p in gw.requests), gw.requests
    assert out == {"total_spend": 1.0, "keys_with_spend": 1}


def test_keys_past_the_first_page_are_counted(monkeypatch):
    # 250 keys at $0.01 span three pages of 100. Stopping after the first would report
    # $1.00 — a number, and a wrong one, which is worse than saying it is unavailable.
    gw = _Gateway([{"spend": 0.01} for _ in range(250)])
    _install(monkeypatch, gw)
    out = _summary()
    assert out == {"total_spend": 2.5, "keys_with_spend": 250}
    assert len(gw.requests) == 3


def test_no_keys_is_a_measured_zero_in_one_request(monkeypatch):
    gw = _Gateway([])
    _install(monkeypatch, gw)
    assert _summary() == {"total_spend": 0.0, "keys_with_spend": 0}
    assert len(gw.requests) == 1


def test_a_page_refused_midway_is_unavailable_not_a_partial_total(monkeypatch):
    gw = _Gateway([{"spend": 0.01} for _ in range(250)], fail_on_page=2)
    _install(monkeypatch, gw)
    out = _summary()
    assert "total_spend" not in out, "a partial sum is a wrong number, not a measurement"
    assert "500" in out["unavailable"]
