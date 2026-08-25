"""Login had no rate limit, no lockout, and no backoff.

The endpoint is on the public internet and verifies a bcrypt hash on every attempt,
so an unthrottled login is both a credential-guessing oracle and a CPU exhaustion
lever. These tests drive the decision logic only — no clock, no network, no store —
so the policy is verifiable without waiting for real time to pass.
"""
import pytest

from app.rate_limit import LoginThrottle


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def throttle(clock):
    return LoginThrottle(clock=clock, max_failures=3, base_lockout=60,
                         max_lockout=600, ip_max_failures=10, ip_window=300)


def _fail(throttle, n, username="alice", ip="10.0.0.1"):
    for _ in range(n):
        throttle.record_failure(username, ip)


def test_a_fresh_attempt_is_allowed(throttle):
    assert throttle.retry_after("alice", "10.0.0.1") is None


def test_attempts_below_the_threshold_stay_allowed(throttle):
    _fail(throttle, 2)
    assert throttle.retry_after("alice", "10.0.0.1") is None


def test_the_account_locks_at_the_threshold(throttle):
    _fail(throttle, 3)
    assert throttle.retry_after("alice", "10.0.0.1") == 60


def test_the_lockout_expires(throttle, clock):
    _fail(throttle, 3)
    clock.advance(61)
    assert throttle.retry_after("alice", "10.0.0.1") is None


def test_each_further_failure_doubles_the_wait(throttle, clock):
    _fail(throttle, 3)
    clock.advance(61)
    throttle.record_failure("alice", "10.0.0.1")
    assert throttle.retry_after("alice", "10.0.0.1") == 120
    clock.advance(121)
    throttle.record_failure("alice", "10.0.0.1")
    assert throttle.retry_after("alice", "10.0.0.1") == 240


def test_the_wait_is_capped(throttle, clock):
    """Without a cap the doubling reaches years, and a locked-out account is
    indistinguishable from a deleted one."""
    _fail(throttle, 3)
    for _ in range(12):
        clock.advance(5)
        throttle.record_failure("alice", "10.0.0.1")
    assert throttle.retry_after("alice", "10.0.0.1") == 600


def test_old_failures_are_forgotten(throttle, clock):
    """Two mistyped passwords last month must not combine with two today to lock a
    real user out. The counter decays; it does not accumulate for the life of the
    process."""
    _fail(throttle, 2)
    clock.advance(10_000)
    _fail(throttle, 2)
    assert throttle.retry_after("alice", "10.0.0.1") is None


def test_a_successful_login_clears_the_account(throttle):
    _fail(throttle, 3)
    throttle.record_success("alice", "10.0.0.1")
    assert throttle.retry_after("alice", "10.0.0.1") is None


def test_one_account_lockout_does_not_lock_another(throttle):
    _fail(throttle, 3, username="alice")
    assert throttle.retry_after("bob", "10.0.0.2") is None


def test_an_unknown_username_is_counted_the_same_as_a_real_one(throttle):
    """Otherwise the throttle itself answers 'does this account exist?' — only a real
    account would ever lock, so a 429 would confirm the guess."""
    _fail(throttle, 3, username="no-such-user")
    assert throttle.retry_after("no-such-user", "10.0.0.1") == 60


def test_usernames_are_matched_case_insensitively(throttle):
    """Otherwise 'Alice', 'ALICE', and 'alice' are three separate budgets against one
    account — the login lookup does not distinguish them."""
    _fail(throttle, 3, username="alice")
    assert throttle.retry_after("ALICE", "10.0.0.1") == 60


def test_spraying_many_usernames_from_one_address_is_blocked(throttle):
    """The per-account counter alone never fires when each guess targets a different
    account, which is what a password-spray does."""
    for i in range(10):
        throttle.record_failure(f"user{i}", "10.0.0.9")
    assert throttle.retry_after("user-fresh", "10.0.0.9") is not None


def test_the_address_budget_is_a_rolling_window(throttle, clock):
    for i in range(9):
        throttle.record_failure(f"user{i}", "10.0.0.9")
    clock.advance(301)
    throttle.record_failure("late", "10.0.0.9")
    assert throttle.retry_after("other", "10.0.0.9") is None


def test_one_address_being_blocked_does_not_block_another(throttle):
    for i in range(10):
        throttle.record_failure(f"user{i}", "10.0.0.9")
    assert throttle.retry_after("someone", "10.0.0.8") is None


def test_a_missing_address_does_not_create_one_shared_bucket(throttle):
    """A proxy that strips the client IP must not put every user of the deployment
    into a single budget that any one of them can exhaust for everyone."""
    for i in range(10):
        throttle.record_failure(f"user{i}", None)
    assert throttle.retry_after("someone", None) is None


def test_expired_entries_do_not_accumulate(throttle, clock):
    """The store is in memory in the fallback path; an unbounded one is a slow leak
    an attacker controls the size of."""
    for i in range(500):
        throttle.record_failure(f"user{i}", f"10.0.{i // 256}.{i % 256}")
    clock.advance(100_000)
    throttle.retry_after("anyone", "10.0.0.1")
    assert throttle.size() < 50


# ── which address the throttle counts ─────────────────────────────────────────
#
# The live cluster runs Traefik with externalTrafficPolicy: Cluster, so the socket
# peer the backend sees is a cluster-internal address — the same one for every
# request on the internet. Counting that would put the whole world in one budget,
# and twenty failures would lock every user out of the product. Verified against the
# running cluster rather than assumed.

from app.rate_limit import client_address


class FakeRequest:
    def __init__(self, peer=None, headers=None):
        self.client = type("C", (), {"host": peer})() if peer else None
        self.headers = headers or {}


def test_without_a_proxy_the_socket_peer_is_the_address():
    assert client_address(FakeRequest(peer="203.0.113.7"), trust_proxy=False) == "203.0.113.7"


def test_behind_a_proxy_the_forwarded_header_is_used():
    req = FakeRequest(peer="10.42.0.107", headers={"x-forwarded-for": "203.0.113.7"})
    assert client_address(req, trust_proxy=True) == "203.0.113.7"


def test_a_client_supplied_forwarded_value_cannot_displace_the_real_one():
    """Traefik appends the peer it saw rather than replacing the header, so a client
    that sends its own X-Forwarded-For ends up on the LEFT. Taking the leftmost entry
    would let anyone choose their own bucket and evade the budget entirely."""
    req = FakeRequest(peer="10.42.0.107",
                      headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2, 203.0.113.7"})
    assert client_address(req, trust_proxy=True) == "203.0.113.7"


def test_a_proxy_that_sends_no_header_falls_back_to_the_peer():
    req = FakeRequest(peer="10.42.0.107")
    assert client_address(req, trust_proxy=True) == "10.42.0.107"


def test_no_request_yields_no_address():
    assert client_address(None, trust_proxy=True) is None


def test_an_empty_header_is_not_an_address():
    req = FakeRequest(peer="10.42.0.107", headers={"x-forwarded-for": " , "})
    assert client_address(req, trust_proxy=True) == "10.42.0.107"
