"""budget-alerts reports gateway-wide spend even when no budget is set.

The Overview's model spend tile first read /settings/ai/spend, which sums only spend
recorded against virtual keys: $0.00 on a deployment whose gateway had spent $0.30,
because none of it went through a key. budget-alerts already reads /global/spend, but
returned that figure only inside `global`, which exists only when a budget is set.
"""
import asyncio

from app.api import ai_backends


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.text = status, payload, str(payload)

    def json(self):
        return self._payload


class _Gateway:
    def __init__(self, global_spend, up=True):
        self.global_spend, self.up = global_spend, up

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        if not self.up:
            raise ConnectionError("gateway down")
        if url.endswith("/global/spend"):
            return _Resp(200, self.global_spend)
        if url.endswith("/key/list"):
            return _Resp(200, {"keys": [], "total_pages": 0})
        return _Resp(404, {})


def _install(monkeypatch, gateway):
    monkeypatch.setattr(ai_backends, "_gateway", lambda: ("http://gw", "sk-test"))
    monkeypatch.setattr(ai_backends.httpx, "AsyncClient", lambda *a, **k: gateway)


def test_spend_total_is_reported_without_a_budget(monkeypatch):
    _install(monkeypatch, _Gateway({"spend": 0.299768, "max_budget": None}))
    out = _run(ai_backends.budget_alerts())
    assert out["spend_total"] == 0.299768
    assert out["global"] is None


def test_spend_total_sits_beside_the_budget_when_one_is_set(monkeypatch):
    _install(monkeypatch, _Gateway({"spend": 40.0, "max_budget": 50.0}))
    out = _run(ai_backends.budget_alerts())
    assert out["spend_total"] == 40.0
    assert out["global"] == {"spend": 40.0, "max_budget": 50.0, "pct": 80.0, "alert": True}


def test_an_unreadable_gateway_is_not_zero_spend(monkeypatch):
    _install(monkeypatch, _Gateway({}, up=False))
    out = _run(ai_backends.budget_alerts())
    assert out["spend_total"] is None


# ── Per-caller caps on the usage rows ────────────────────────────────────────

class _CustomerGateway(_Gateway):
    """Adds /customer/list to the fake, the way the proxy answers it."""

    def __init__(self, customers, up=True):
        super().__init__({}, up=up)
        self.customers = customers

    async def get(self, url, headers=None, params=None):
        if url.endswith("/customer/list"):
            if not self.up:
                raise ConnectionError("gateway down")
            return _Resp(200, self.customers)
        return await super().get(url, headers=headers, params=params)


def test_usage_rows_carry_each_callers_cap(monkeypatch):
    _install(monkeypatch, _CustomerGateway([
        {"user_id": "u1", "max_budget": 5.0},
        {"user_id": "u2", "litellm_budget_table": {"max_budget": 0.5}},
        {"user_id": "u3"},
    ]))
    rows = _run(ai_backends._with_user_budgets(
        [{"user": "u1"}, {"user": "u2"}, {"user": "u3"}, {"user": "unattributed"}]))
    assert [(r["user"], r["max_budget"]) for r in rows] == [
        ("u1", 5.0), ("u2", 0.5), ("u3", None), ("unattributed", None)]


def test_an_unreadable_gateway_leaves_caps_unknown_not_unlimited(monkeypatch):
    _install(monkeypatch, _CustomerGateway([], up=False))
    rows = _run(ai_backends._with_user_budgets([{"user": "u1", "spend": 1.0}]))
    assert rows == [{"user": "u1", "spend": 1.0, "max_budget": None}]
