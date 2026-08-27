"""Durable record of infrastructure state changes. Design:
docs/superpowers/specs/2026-08-27-system-event-history-design.md

Kubernetes Events expire after an hour and are only reachable through pods that still
exist, so the pod you want to ask about — the one that died — is the one you cannot.
This module decides what is worth keeping and how a repeating condition stays one row.

Everything decidable without a cluster or a database is a pure function here, tested in
tests/test_system_events.py. The impure edges live at the bottom and stay thin.
"""
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("system_events")

# Fixed 64-bit key for pg_try_advisory_lock, distinct from rag_scheduler's. Same
# session-scoped caveat: this holds because the backend speaks to Postgres directly.
# A transaction-mode pooler in front would break the exclusion.
LOCK_KEY = 7233183143331076965

# Kubernetes reasons we can name. The allowlist decides what gets a *name*, not what
# gets *recorded* — see classify_k8s_event.
KEEP_REASONS = {
    "Unhealthy":        ("probe_failure",      "warning"),
    "OOMKilling":       ("oom_kill",           "critical"),
    "OOMKilled":        ("oom_kill",           "critical"),
    "ErrImagePull":     ("image_pull_failure", "warning"),
    "ImagePullBackOff": ("image_pull_failure", "warning"),
    "FailedScheduling": ("schedule_failure",   "warning"),
    "FailedMount":      ("mount_failure",      "warning"),
    "BackOff":          ("crash_backoff",      "warning"),
    "Evicted":          ("eviction",           "critical"),
    "NodeNotReady":     ("node_not_ready",     "critical"),
    "Failed":           ("container_failure",  "warning"),
}

# "Failed" is Kubernetes' catch-all; the message is what distinguishes an image it
# could not pull from a container that would not start.
_IMAGE_PULL_HINTS = ("errimagepull", "imagepullbackoff", "pull image", "pulling image")

# Boot time is derived from uptime against the wall clock, so it wobbles by a second or
# two on every read. Without a tolerance every tick would report a reboot.
_BOOT_TOLERANCE = timedelta(seconds=120)

# Retention has a floor, not an off switch: unbounded growth is not acceptable on a
# single node.
_MIN_RETENTION_DAYS = 1


def dedup_key(source: str, kind: str, obj: str, discriminator: str = "") -> str:
    """Stable identity of one condition.

    This is what makes polling idempotent — re-reading the same window has to land on
    the row already there rather than writing a second one.
    """
    raw = "\x1f".join((source, kind, obj, discriminator))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def classify_k8s_event(event: dict) -> "dict | None":
    """A Kubernetes Event as something worth keeping, or None.

    Normal events are dropped whole. A cluster emits Scheduled/Pulled/Created/Started
    on every rollout; keeping them buries the one line that mattered.

    Warnings are always kept, named or not. A warning nobody anticipated is exactly the
    one worth having when something has gone wrong in a way we did not predict, so the
    allowlist controls naming and never suppression.
    """
    if (event.get("type") or "") != "Warning":
        return None

    reason = event.get("reason") or ""
    message = event.get("message") or ""
    kind, severity = KEEP_REASONS.get(reason, ("unknown", "warning"))

    if kind == "container_failure" and any(h in message.lower() for h in _IMAGE_PULL_HINTS):
        kind = "image_pull_failure"

    obj = event.get("object") or ""
    return {
        "dedup_key": dedup_key("kubernetes", kind, obj, reason),
        "kind": kind,
        "severity": severity,
        "source": "kubernetes",
        "object": obj,
        "message": message[:2000],
        "details": {"reason": reason},
    }


def restart_events(previous: dict, current: dict, now: datetime) -> list:
    """Pods whose restart counter rose between two observations.

    Only pods present in both are compared. A pod seen for the first time contributes
    nothing: its restarts happened before we were watching, and replaying them would
    make every backend deploy look like a cluster-wide incident.
    """
    events = []
    for name, count in sorted(current.items()):
        before = previous.get(name)
        if before is None or count <= before:
            continue
        events.append({
            "dedup_key": dedup_key("kubernetes", "pod_restart", name, str(count)),
            "kind": "pod_restart",
            "severity": "warning",
            "source": "kubernetes",
            "object": name,
            "message": f"Container restarted ({count} total)",
            "details": {"restart_count": count, "delta": count - before},
            "last_seen": now,
        })
    return events


def reboot_event(previous_boot: "datetime | None", current_boot: datetime) -> "dict | None":
    """A node reboot, inferred from boot time moving forward.

    Detected after the fact by construction: nothing collects while the backend is
    down. The cause is therefore not ours to give, and the row says so — inferring one
    would be worse than its absence, because it would be believed.
    """
    if previous_boot is None:
        return None
    if current_boot - previous_boot <= _BOOT_TOLERANCE:
        return None
    return {
        "dedup_key": dedup_key("node", "node_reboot", "node", current_boot.isoformat()),
        "kind": "node_reboot",
        "severity": "critical",
        "source": "node",
        "object": "node",
        "message": f"Node restarted at {current_boot.isoformat(timespec='seconds')} "
                   f"— cause not recorded",
        "details": {"cause_recorded": False, "booted_at": current_boot.isoformat(),
                    "previous_boot": previous_boot.isoformat()},
        "last_seen": current_boot,
    }


def merge_repeat(existing: dict, last_seen: datetime, count: int) -> dict:
    """One condition that keeps happening stays one row.

    Neither counter moves backwards. Kubernetes restarts its own event counters when it
    recreates an Event object, and taking the smaller number would make a condition
    that is still firing look like it had stopped.
    """
    return {
        "first_seen": existing["first_seen"],
        "last_seen": max(existing["last_seen"], last_seen),
        "count": max(existing["count"], count),
    }


def retention_cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=max(int(days), _MIN_RETENTION_DAYS))


def retention_days() -> int:
    try:
        return max(int(os.getenv("SYSTEM_EVENTS_RETENTION_DAYS", "30")), _MIN_RETENTION_DAYS)
    except (TypeError, ValueError):
        return 30


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── cluster adaptation ────────────────────────────────────────────────────────
# The Kubernetes client returns objects; the classifier above takes dicts. Keeping the
# translation here, and tested, means a rename on either side fails a test rather than
# quietly producing an empty event history.

def adapt_k8s_events(events, now: "datetime | None" = None) -> list:
    out = []
    for e in events or []:
        stamp = getattr(e, "last_timestamp", None) or getattr(e, "event_time", None)
        out.append({
            "type": getattr(e, "type", "") or "",
            "reason": getattr(e, "reason", "") or "",
            "message": getattr(e, "message", "") or "",
            "object": getattr(getattr(e, "involved_object", None), "name", "") or "",
            "count": getattr(e, "count", 1) or 1,
            # An Event the apiserver has seen once may carry no last_timestamp. Dropping
            # those would lose first occurrences, which are the interesting ones.
            "last_timestamp": stamp or now or utcnow(),
        })
    return out


def adapt_pod_restarts(pods) -> dict:
    """Restart counter per pod, summed across containers.

    A pod with a sidecar restarts as a pod. The Services page reads only the first
    container's counter, which misses a sidecar crash loop entirely.
    """
    counts = {}
    for p in pods or []:
        statuses = getattr(getattr(p, "status", None), "container_statuses", None) or []
        counts[p.metadata.name] = sum(getattr(s, "restart_count", 0) or 0 for s in statuses)
    return counts


def boot_time_from_uptime(uptime_text: str, now: datetime) -> "datetime | None":
    """When the node booted, from /proc/uptime.

    /proc/uptime is not namespaced, so inside the pod it reports the *node's* uptime.
    That is the only reason a container can answer "when did this node restart".
    """
    try:
        seconds = float((uptime_text or "").split()[0])
    except (IndexError, ValueError):
        return None
    return now - timedelta(seconds=seconds)


# ── storage ───────────────────────────────────────────────────────────────────

# The ON CONFLICT clause is the SQL half of merge_repeat(): neither counter moves
# backwards. test_the_upsert_matches_merge_repeat holds the two together, because a
# divergence here would look like a condition that had stopped firing.
_UPSERT = """
INSERT INTO system_events
    (dedup_key, kind, severity, source, object, message, details,
     first_seen, last_seen, occurrences)
VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $8, $9)
ON CONFLICT (dedup_key) DO UPDATE SET
    last_seen   = GREATEST(system_events.last_seen, EXCLUDED.last_seen),
    occurrences = GREATEST(system_events.occurrences, EXCLUDED.occurrences),
    message     = EXCLUDED.message,
    details     = EXCLUDED.details
RETURNING (xmax = 0) AS inserted
"""


async def record(conn, event: dict, now: datetime) -> bool:
    """Write one event. Returns True if it was new rather than a repeat."""
    import json
    return await conn.fetchval(
        _UPSERT,
        event["dedup_key"], event["kind"], event["severity"], event["source"],
        event.get("object", ""), event.get("message", ""),
        json.dumps(event.get("details") or {}),
        event.get("last_seen") or now,
        int(event.get("occurrences") or 1),
    )


async def load_state(conn, key: str):
    import json
    raw = await conn.fetchval("SELECT value FROM system_event_state WHERE key = $1", key)
    if raw is None:
        return None
    return json.loads(raw) if isinstance(raw, str) else raw


async def save_state(conn, key: str, value) -> None:
    import json
    await conn.execute(
        """INSERT INTO system_event_state (key, value, updated_at)
           VALUES ($1, $2::jsonb, now())
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
        key, json.dumps(value))


async def prune(conn, cutoff: datetime, ceiling: int = 20000) -> int:
    """Drop what is older than the window, then anything above the row ceiling.

    Two limits rather than one: a burst of a thousand distinct pod names inside the
    window would otherwise sit there until the window passed.
    """
    removed = await conn.execute("DELETE FROM system_events WHERE last_seen < $1", cutoff)
    await conn.execute(
        """DELETE FROM system_events WHERE id IN (
               SELECT id FROM system_events ORDER BY last_seen DESC OFFSET $1)""",
        ceiling)
    try:
        return int(str(removed).rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0


# ── collection ────────────────────────────────────────────────────────────────

def read_uptime() -> str:
    try:
        with open("/proc/uptime", "r") as fh:
            return fh.read()
    except OSError:
        return ""


def observe(now: datetime) -> dict:
    """One read of the cluster and the node. Never raises: a tick that cannot see the
    cluster should record nothing, not kill the loop."""
    events, restarts = [], {}
    try:
        from app.api.services import NAMESPACE, core_v1
        events = adapt_k8s_events(
            core_v1.list_namespaced_event(namespace=NAMESPACE).items, now=now)
        restarts = adapt_pod_restarts(core_v1.list_namespaced_pod(namespace=NAMESPACE).items)
    except Exception as e:
        logger.debug("cluster read failed: %s", e)
    return {"events": events, "restarts": restarts,
            "boot_time": boot_time_from_uptime(read_uptime(), now)}


async def tick(pool) -> int:
    """One collection pass. Returns the number of events newly recorded.

    Single-leader via advisory lock: with two replicas both would otherwise write the
    same conditions, and while the dedup key makes that harmless it doubles the work.
    """
    async with pool.acquire() as c:
        if not await c.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            return 0
        try:
            now = utcnow()
            seen = observe(now)

            pending = []
            for raw in seen["events"]:
                classified = classify_k8s_event(raw)
                if classified:
                    classified["last_seen"] = raw["last_timestamp"]
                    classified["occurrences"] = raw["count"]
                    pending.append(classified)

            previous = await load_state(c, "pod_restarts") or {}
            pending += restart_events(previous, seen["restarts"], now)

            previous_boot = await load_state(c, "boot_time")
            if seen["boot_time"] is not None:
                if previous_boot:
                    reboot = reboot_event(datetime.fromisoformat(previous_boot),
                                          seen["boot_time"])
                    if reboot:
                        pending.append(reboot)
                await save_state(c, "boot_time", seen["boot_time"].isoformat())

            recorded = 0
            for event in pending:
                try:
                    if await record(c, event, now):
                        recorded += 1
                except Exception as e:
                    logger.warning("could not record %s: %s", event.get("kind"), e)

            # Saved after the comparison, not before: a crash between the two costs one
            # tick of detection, while the reverse would drop the restart entirely.
            await save_state(c, "pod_restarts", seen["restarts"])
            await prune(c, retention_cutoff(now, retention_days()))
            return recorded
        finally:
            await c.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)


async def run_collector(pool) -> None:
    import asyncio
    tick_seconds = int(os.getenv("SYSTEM_EVENTS_TICK_SECONDS", "120"))
    logger.info("system event collector started (tick=%ss)", tick_seconds)
    while True:
        await asyncio.sleep(tick_seconds)
        try:
            n = await tick(pool)
            if n:
                logger.info("recorded %s new system event(s)", n)
        except Exception as e:                       # never let the loop die
            logger.warning("system event tick error: %s", e)


# ── query filters ─────────────────────────────────────────────────────────────

def build_filters(hours: int, severity: str = None, kind: str = None,
                  source: str = None) -> tuple:
    """(where clause, positional args) for a window plus optional equality filters.

    Placeholder numbering is positional and getting it wrong does not raise — it binds
    the wrong value to the wrong column, which reads to the user as "no events
    matched". Built in one place, and tested, for that reason.
    """
    args = [str(int(hours))]
    clauses = ["last_seen >= now() - ($1 || ' hours')::interval"]
    for column, value in (("severity", severity), ("kind", kind), ("source", source)):
        if value:
            args.append(value)
            clauses.append(f"{column} = ${len(args)}")
    return " AND ".join(clauses), args
