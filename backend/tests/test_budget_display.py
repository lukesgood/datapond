"""The cap the console shows is the cap that is enforced.

A cap set through DataPond lives in Postgres and wins over the gateway's (app/ai_budget).
The gateway does not keep a cap of 0 (it reports None), so showing the gateway's value
said "no cap" while every call was refused with 402 (seen live 2026-10-19).
"""
import asyncio

import app.ai_budget as ai_budget
import app.api.ai_backends as ai_backends
import app.api.ai_budgets as ai_budgets


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _gateway(monkeypatch, *, info=None, customers=()):
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, url, **k):
            if url.endswith("/customer/info"):
                return _Resp(404, {}) if info is None else _Resp(200, info)
            return _Resp(200, list(customers))

    for mod in (ai_budgets, ai_backends):
        monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(mod, "_gateway", lambda: ("http://gw", "k"))


def _shared(monkeypatch, caps=None, fail=False):
    async def _caps():
        if fail:
            raise RuntimeError("db down")
        return dict(caps or {})
    monkeypatch.setattr(ai_budget, "shared_caps", _caps)


async def _no_names(users):
    return [{**u, "name": None} for u in users]


def test_one_caller_shows_a_zero_cap_the_gateway_does_not_keep(monkeypatch):
    _gateway(monkeypatch, info={"user_id": "a", "spend": 0.01, "max_budget": None})
    _shared(monkeypatch, {"a": 0.0})
    out = _run(ai_budgets.get_budget("a"))
    assert out["max_budget"] == 0.0 and out["spend"] == 0.01


def test_one_caller_unknown_to_the_gateway_still_shows_its_cap(monkeypatch):
    _gateway(monkeypatch, info=None)
    _shared(monkeypatch, {"a": 5.0})
    assert _run(ai_budgets.get_budget("a"))["max_budget"] == 5.0


def test_without_a_shared_cap_the_gateways_cap_shows(monkeypatch):
    _gateway(monkeypatch, info={"user_id": "a", "spend": 1.0, "max_budget": 3.0})
    _shared(monkeypatch, {})
    assert _run(ai_budgets.get_budget("a"))["max_budget"] == 3.0


def test_the_list_shows_shared_caps_and_callers_the_gateway_has_not_seen(monkeypatch):
    _gateway(monkeypatch, customers=[{"user_id": "a", "spend": 0.5, "max_budget": None},
                                     {"user_id": "b", "spend": 1.0, "max_budget": 9.0}])
    _shared(monkeypatch, {"a": 0.0, "c": 2.0})
    monkeypatch.setattr(ai_backends, "_with_user_names", _no_names)
    rows = {c["user_id"]: c for c in _run(ai_budgets.list_budgets())["customers"]}
    assert (rows["a"]["max_budget"], rows["b"]["max_budget"], rows["c"]["max_budget"]) == (0.0, 9.0, 2.0)
    assert rows["c"]["spend"] == 0.0


def test_the_list_says_so_when_shared_caps_cannot_be_read(monkeypatch):
    _gateway(monkeypatch, customers=[{"user_id": "a", "spend": 0.5, "max_budget": None}])
    _shared(monkeypatch, fail=True)
    monkeypatch.setattr(ai_backends, "_with_user_names", _no_names)
    out = _run(ai_budgets.list_budgets())
    assert out["unavailable"]


def test_spend_rows_show_the_enforced_cap(monkeypatch):
    _gateway(monkeypatch, customers=[{"user_id": "a", "max_budget": None},
                                     {"user_id": "b", "max_budget": 4.0}])
    _shared(monkeypatch, {"a": 0.0})
    rows = _run(ai_backends._with_user_budgets([{"user": "a"}, {"user": "b"}, {"user": "z"}]))
    assert [r["max_budget"] for r in rows] == [0.0, 4.0, None]
