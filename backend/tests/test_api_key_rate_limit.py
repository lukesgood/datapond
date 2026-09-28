"""Per-key request budget for service-account API keys.

A key is what gets copied into an agent's config, and an agent in a loop calls as
fast as the network lets it. Every call can reach the database, pgvector, and a
paid model. Before this there was no limit at all on API-key traffic: the only
throttle in the product counted failed logins.
"""
from fastapi.testclient import TestClient

from app.rate_limit import ApiKeyRateLimit


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_calls_within_the_budget_pass():
    limiter = ApiKeyRateLimit(clock=_Clock(), per_minute=3)
    assert [limiter.check("k1") for _ in range(3)] == [None, None, None]


def test_the_call_past_the_budget_is_told_how_long_to_wait():
    clock = _Clock()
    limiter = ApiKeyRateLimit(clock=clock, per_minute=60)
    for _ in range(60):
        assert limiter.check("k1") is None
    wait = limiter.check("k1")
    assert wait is not None and 1 <= wait <= 2


def test_the_budget_refills_with_time():
    clock = _Clock()
    limiter = ApiKeyRateLimit(clock=clock, per_minute=60)
    for _ in range(60):
        limiter.check("k1")
    assert limiter.check("k1") is not None
    clock.now += 1.0                       # one token per second at 60/min
    assert limiter.check("k1") is None
    assert limiter.check("k1") is not None


def test_keys_do_not_share_a_budget():
    limiter = ApiKeyRateLimit(clock=_Clock(), per_minute=1)
    assert limiter.check("k1") is None
    assert limiter.check("k1") is not None
    assert limiter.check("k2") is None


def test_zero_turns_the_limit_off():
    limiter = ApiKeyRateLimit(clock=_Clock(), per_minute=0)
    assert all(limiter.check("k1") is None for _ in range(10_000))


def test_idle_keys_are_forgotten():
    clock = _Clock()
    limiter = ApiKeyRateLimit(clock=clock, per_minute=10)
    for i in range(50):
        limiter.check(f"k{i}")
    clock.now += 3600
    limiter.check("fresh")
    assert limiter.size() == 1


def test_default_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("API_KEY_RATE_LIMIT_PER_MINUTE", "2")
    limiter = ApiKeyRateLimit(clock=_Clock())
    assert limiter.check("k") is None and limiter.check("k") is None
    assert limiter.check("k") is not None


# ── through the middleware ────────────────────────────────────────────────────

def _client(monkeypatch, user, per_minute):
    import main
    from app import rate_limit
    from app.api import auth

    async def _user(_creds):
        return user
    monkeypatch.setattr(auth, "get_current_user", _user)
    monkeypatch.setattr(rate_limit, "_api_key_limiter",
                        ApiKeyRateLimit(clock=_Clock(), per_minute=per_minute))
    return TestClient(main.app)


SERVICE = {"id": "svc-1", "username": "svc-agent", "role": "ai_engineer",
           "auth_method": "service", "api_key_id": "key-1", "permissions": []}
PERSON = {"id": "u-1", "username": "ada", "role": "admin"}


def test_a_key_over_its_budget_gets_429_with_retry_after(monkeypatch):
    client = _client(monkeypatch, SERVICE, per_minute=2)
    headers = {"Authorization": "Bearer dp_sk_whatever"}
    first = [client.get("/api/no-such-route", headers=headers).status_code for _ in range(2)]
    assert 429 not in first
    r = client.get("/api/no-such-route", headers=headers)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert "rate limit" in r.json()["detail"].lower()


def test_a_person_is_not_held_to_the_key_budget(monkeypatch):
    client = _client(monkeypatch, PERSON, per_minute=1)
    headers = {"Authorization": "Bearer a.jwt.token"}
    codes = [client.get("/api/no-such-route", headers=headers).status_code for _ in range(5)]
    assert 429 not in codes
