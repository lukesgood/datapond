"""Login throttling: per-account lockout with backoff, plus a per-address budget.

Login was unthrottled. The endpoint is public and verifies a bcrypt hash on every
attempt, so that is both a credential-guessing oracle and a way to spend the CPU of
a single-node deployment from anywhere.

Two counters, because one is not enough:

  **per account** — catches guessing a single password. Locks after a few failures
  and doubles the wait each time, so a patient attacker gets slower, not stopped at
  a fixed rate they can plan around.

  **per address** — catches the opposite shape: one guess against each of many
  accounts (a spray), where the per-account counter never fires.

The decision logic here is pure and takes its clock as an argument, so the policy is
tested without sleeping. Storage is deliberately separate: see `store` below.
"""
import os
import threading
from typing import Callable, Dict, Optional, Tuple


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


class LoginThrottle:
    """Decides whether an attempt may proceed, and for how long it may not.

    Not a general rate limiter. It counts *failures* only: a working user is never
    slowed down, however often they sign in.
    """

    def __init__(self, clock: Callable[[], float],
                 max_failures: Optional[int] = None,
                 base_lockout: Optional[int] = None,
                 max_lockout: Optional[int] = None,
                 ip_max_failures: Optional[int] = None,
                 ip_window: Optional[int] = None):
        self._clock = clock
        self._max_failures = max_failures if max_failures is not None \
            else _int_env("LOGIN_MAX_FAILURES", 5)
        self._base_lockout = base_lockout if base_lockout is not None \
            else _int_env("LOGIN_LOCKOUT_SECONDS", 60)
        self._max_lockout = max_lockout if max_lockout is not None \
            else _int_env("LOGIN_LOCKOUT_MAX_SECONDS", 900)
        self._ip_max = ip_max_failures if ip_max_failures is not None \
            else _int_env("LOGIN_IP_MAX_FAILURES", 20)
        self._ip_window = ip_window if ip_window is not None \
            else _int_env("LOGIN_IP_WINDOW_SECONDS", 300)
        self._lock = threading.Lock()
        # key -> (failure count, moment the current lockout ends, last failure)
        self._accounts: Dict[str, Tuple[int, float, float]] = {}
        # address -> list of failure timestamps inside the window
        self._addresses: Dict[str, list] = {}

    # ── keys ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _account_key(username: Optional[str]) -> str:
        # Lower-cased: the login lookup does not distinguish case, so neither may the
        # budget, or "Alice" and "alice" are two allowances against one account.
        return (username or "").strip().lower()

    # ── decisions ─────────────────────────────────────────────────────────────

    def retry_after(self, username: Optional[str], ip: Optional[str]) -> Optional[int]:
        """Seconds this attempt must wait, or None if it may proceed."""
        now = self._clock()
        with self._lock:
            self._evict(now)
            waits = []

            _count, until, _last = self._accounts.get(
                self._account_key(username), (0, 0.0, 0.0))
            if until > now:
                waits.append(until - now)

            if ip:
                hits = self._addresses.get(ip, ())
                if len(hits) >= self._ip_max:
                    waits.append(min(hits) + self._ip_window - now)

        positive = [w for w in waits if w > 0]
        return int(round(max(positive))) if positive else None

    def record_failure(self, username: Optional[str], ip: Optional[str]) -> None:
        now = self._clock()
        with self._lock:
            self._evict(now)
            key = self._account_key(username)
            count, _until, _last = self._accounts.get(key, (0, 0.0, 0.0))
            count += 1
            if count >= self._max_failures:
                # Doubles per failure past the threshold, capped. The cap matters:
                # without it a long-running deployment can lock an account for years.
                over = count - self._max_failures
                wait = min(self._base_lockout * (2 ** over), self._max_lockout)
                self._accounts[key] = (count, now + wait, now)
            else:
                self._accounts[key] = (count, 0.0, now)

            # A missing address is not a bucket. Behind a proxy that strips the client
            # IP every user would share one budget, and any one of them could exhaust
            # it for everyone — a denial of service handed to the first attacker.
            if ip:
                self._addresses.setdefault(ip, []).append(now)

    def record_success(self, username: Optional[str], ip: Optional[str]) -> None:
        """Proving the password clears that account's history.

        The address budget is left alone on purpose: one valid credential does not
        make the other forty guesses from that address innocent.
        """
        with self._lock:
            self._accounts.pop(self._account_key(username), None)

    # ── housekeeping ──────────────────────────────────────────────────────────

    def _evict(self, now: float) -> None:
        """Drop what can no longer affect a decision.

        In the fallback path this store is process memory whose keys an attacker
        chooses, so it has to shrink on its own. Called from both entry points, so
        eviction happens under traffic rather than on a timer.
        """
        cutoff = now - self._ip_window
        for ip in [k for k, hits in self._addresses.items() if not hits or max(hits) < cutoff]:
            del self._addresses[ip]
        for ip, hits in self._addresses.items():
            if hits[0] < cutoff:
                self._addresses[ip] = [t for t in hits if t >= cutoff]

        # Forget an account once its last failure is old and it is no longer locked.
        # Two conditions, and the first is the one an earlier version missed: it
        # evicted only entries that had been *locked*, so an attacker who failed once
        # against each of a million usernames left a million entries that never
        # expired. Keying eviction on the last failure covers both shapes.
        #
        # This also decays the counter, which is the behaviour a user wants: two
        # mistyped passwords last month must not combine with three today.
        stale = now - max(self._max_lockout, self._ip_window)
        for key in [k for k, (_c, until, last) in self._accounts.items()
                    if last < stale and until <= now]:
            del self._accounts[key]

    def size(self) -> int:
        with self._lock:
            return len(self._accounts) + len(self._addresses)


def client_address(request, trust_proxy: Optional[bool] = None) -> Optional[str]:
    """The address to count this attempt against.

    Which value is correct depends on the deployment, and getting it wrong is not a
    small error in either direction. The live AWS reference runs Traefik with
    `externalTrafficPolicy: Cluster`, so the socket peer is a cluster-internal
    address identical for every request that arrives from the internet — counting it
    would put the entire world in one budget, and a few dozen failed logins would
    lock every user out of the product.

    Behind such a proxy the client is in `X-Forwarded-For`. Traefik *appends* the
    peer it saw rather than replacing the header, so a client that sends its own
    `X-Forwarded-For` lands on the left and the value our proxy added is on the
    right. Reading the leftmost entry — the usual reflex — would let any caller pick
    their own bucket and evade the budget completely. With exactly one trusted hop,
    the rightmost entry is the one nobody upstream could have chosen.

    Helm sets LOGIN_TRUST_PROXY from `ingress.enabled`, because that is precisely the
    question being asked: is there a proxy in front of this?
    """
    if request is None:
        return None
    if trust_proxy is None:
        trust_proxy = os.getenv("LOGIN_TRUST_PROXY", "false").lower() in ("1", "true", "yes")

    if trust_proxy:
        try:
            forwarded = request.headers.get("x-forwarded-for") or ""
        except Exception:
            forwarded = ""
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]

    client = getattr(request, "client", None)
    return getattr(client, "host", None) if client is not None else None
