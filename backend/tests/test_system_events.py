"""The pure logic behind Infrastructure → Events.

Everything decidable without Kubernetes or a database lives in app.system_events as
a function, and is tested here. The impure edges — the cluster read, the upsert, the
loop — stay thin enough to read.
"""
from datetime import datetime, timedelta, timezone

from app.system_events import (
    KEEP_REASONS,
    classify_k8s_event,
    dedup_key,
    merge_repeat,
    reboot_event,
    restart_events,
    retention_cutoff,
)


def _now():
    return datetime(2026, 8, 27, 6, 40, tzinfo=timezone.utc)


# ── dedup_key ─────────────────────────────────────────────────────────────────

def test_same_condition_yields_the_same_key():
    """A condition that repeats is one row that counts, not N rows.

    The key is what makes polling idempotent: re-reading the same window has to
    land on the row already there.
    """
    a = dedup_key("kubernetes", "probe_failure", "backend-7f4bfd95fd-tsd2d")
    b = dedup_key("kubernetes", "probe_failure", "backend-7f4bfd95fd-tsd2d")
    assert a == b


def test_different_objects_do_not_collide():
    a = dedup_key("kubernetes", "probe_failure", "backend-7f4bfd95fd-tsd2d")
    b = dedup_key("kubernetes", "probe_failure", "backend-7f4bfd95fd-pphv2")
    assert a != b


def test_different_kinds_on_one_object_do_not_collide():
    a = dedup_key("kubernetes", "probe_failure", "litellm-794fd6c585-v985s")
    b = dedup_key("kubernetes", "oom_kill", "litellm-794fd6c585-v985s")
    assert a != b


def test_a_discriminator_separates_otherwise_identical_conditions():
    """Restart 7 and restart 8 on one pod are two events, not one that repeats."""
    a = dedup_key("kubernetes", "pod_restart", "valkey-8468bfb49f-vghtk", "7")
    b = dedup_key("kubernetes", "pod_restart", "valkey-8468bfb49f-vghtk", "8")
    assert a != b


# ── classify_k8s_event ────────────────────────────────────────────────────────

def test_noise_is_dropped():
    """Normal lifecycle chatter is not an event history.

    A cluster produces Scheduled/Pulled/Created/Started on every single rollout. Keeping
    them buries the one line that mattered.
    """
    for reason in ("Scheduled", "Pulled", "Created", "Started", "SuccessfulCreate"):
        assert classify_k8s_event({"type": "Normal", "reason": reason,
                                   "object": "backend-x", "message": ""}) is None


def test_probe_failure_is_kept_as_a_warning():
    out = classify_k8s_event({
        "type": "Warning", "reason": "Unhealthy", "object": "backend-7f4bfd95fd-tsd2d",
        "message": 'Readiness probe failed: Get "http://10.42.0.105:8000/health/ready": '
                   "context deadline exceeded",
    })
    assert out is not None
    assert out["kind"] == "probe_failure"
    assert out["severity"] == "warning"
    assert out["source"] == "kubernetes"


def test_oom_kill_is_critical():
    """An OOMKill on a single node is the difference between "it restarted" and
    "the node is undersized", so it does not share a severity with a slow probe."""
    out = classify_k8s_event({"type": "Warning", "reason": "OOMKilling",
                              "object": "litellm-x", "message": "Memory cgroup out of memory"})
    assert out["kind"] == "oom_kill"
    assert out["severity"] == "critical"


def test_image_pull_failure_is_kept():
    out = classify_k8s_event({"type": "Warning", "reason": "Failed", "object": "backend-x",
                              "message": 'Error: ErrImagePull'})
    assert out["kind"] == "image_pull_failure"


def test_scheduling_failure_is_kept():
    out = classify_k8s_event({"type": "Warning", "reason": "FailedScheduling",
                              "object": "backend-x", "message": "0/1 nodes are available"})
    assert out["kind"] == "schedule_failure"


def test_an_unknown_warning_is_kept_rather_than_silently_dropped():
    """The allowlist decides what is *named*, not what is *recorded*.

    A warning nobody anticipated is exactly the one worth having when something has
    gone wrong in a way we did not predict.
    """
    out = classify_k8s_event({"type": "Warning", "reason": "SomethingNewFailed",
                              "object": "backend-x", "message": "..."})
    assert out is not None
    assert out["severity"] == "warning"


def test_every_named_reason_classifies():
    """The allowlist and the classifier cannot drift apart."""
    for reason in KEEP_REASONS:
        out = classify_k8s_event({"type": "Warning", "reason": reason,
                                  "object": "o", "message": "m"})
        assert out is not None, reason
        assert out["kind"] != "unknown", reason


# ── restart_events ────────────────────────────────────────────────────────────

def test_a_rising_restart_counter_is_an_event():
    events = restart_events({"valkey-x": 6}, {"valkey-x": 7}, _now())
    assert len(events) == 1
    assert events[0]["kind"] == "pod_restart"
    assert "7" in events[0]["message"]


def test_an_unchanged_counter_is_not_an_event():
    assert restart_events({"valkey-x": 7}, {"valkey-x": 7}, _now()) == []


def test_a_pod_seen_for_the_first_time_does_not_backfill_its_restarts():
    """Restarts that happened before we were watching are not events we observed.

    Without this, every backend deploy would replay the whole restart history of
    every pod as if it had just happened.
    """
    assert restart_events({}, {"litellm-x": 7}, _now()) == []


def test_a_replaced_pod_starting_at_zero_is_not_a_negative_event():
    assert restart_events({"backend-old": 3}, {"backend-new": 0}, _now()) == []


def test_a_counter_that_jumps_reports_the_jump():
    events = restart_events({"valkey-x": 5}, {"valkey-x": 8}, _now())
    assert len(events) == 1
    assert events[0]["details"]["delta"] == 3


# ── reboot_event ──────────────────────────────────────────────────────────────

def test_a_boot_time_moving_forward_is_a_reboot():
    before = _now() - timedelta(days=2)
    after = _now() - timedelta(hours=4, minutes=52)
    event = reboot_event(before, after)
    assert event is not None
    assert event["kind"] == "node_reboot"
    assert event["severity"] == "critical"


def test_the_reboot_row_says_the_cause_is_not_recorded():
    """Nothing collects while the backend is down, so the cause is not ours to give.

    Inferring one would be worse than its absence, because it would be believed.
    """
    event = reboot_event(_now() - timedelta(days=2), _now() - timedelta(hours=4))
    assert event["details"]["cause_recorded"] is False


def test_a_steady_boot_time_is_not_a_reboot():
    boot = _now() - timedelta(days=2)
    assert reboot_event(boot, boot) is None


def test_a_first_observation_is_not_a_reboot():
    assert reboot_event(None, _now() - timedelta(hours=4)) is None


def test_clock_jitter_of_a_few_seconds_is_not_a_reboot():
    """Boot time is derived from uptime against wall clock, so it wobbles by a second
    or two on every read. Without a tolerance this reports a reboot every tick."""
    boot = _now() - timedelta(days=2)
    assert reboot_event(boot, boot + timedelta(seconds=3)) is None


# ── merge_repeat ──────────────────────────────────────────────────────────────

def test_a_repeat_advances_last_seen_and_keeps_first_seen():
    first = _now() - timedelta(hours=3)
    existing = {"first_seen": first, "last_seen": first, "count": 1}
    merged = merge_repeat(existing, last_seen=_now(), count=4)
    assert merged["first_seen"] == first
    assert merged["last_seen"] == _now()
    assert merged["count"] == 4


def test_a_repeat_never_moves_a_counter_backwards():
    """Kubernetes restarts its own event counters when it recreates an Event object.
    Taking the smaller number would make a condition look like it stopped repeating."""
    first = _now() - timedelta(hours=3)
    existing = {"first_seen": first, "last_seen": _now(), "count": 9}
    merged = merge_repeat(existing, last_seen=_now() - timedelta(hours=1), count=2)
    assert merged["count"] == 9
    assert merged["last_seen"] == _now()


# ── retention ─────────────────────────────────────────────────────────────────

def test_the_cutoff_is_the_retention_window_back_from_now():
    assert retention_cutoff(_now(), 30) == _now() - timedelta(days=30)


def test_retention_cannot_be_disabled_by_a_zero_or_negative_setting():
    """Unbounded growth is not acceptable on a single node, so the setting has a
    floor rather than an off switch."""
    assert retention_cutoff(_now(), 0) < _now()
    assert retention_cutoff(_now(), -5) < _now()


# ── cluster adaptation ────────────────────────────────────────────────────────
# The Kubernetes client returns objects, not dicts. This seam is where the shape the
# classifier expects meets the shape the cluster gives, and it is worth a test because
# a rename on either side would otherwise surface as an empty event history.

class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _k8s_event(reason, message, obj_name, type_="Warning", count=1):
    return _Obj(type=type_, reason=reason, message=message, count=count,
                involved_object=_Obj(name=obj_name),
                last_timestamp=_now())


def test_cluster_events_are_adapted_to_what_the_classifier_expects():
    from app.system_events import adapt_k8s_events

    out = adapt_k8s_events([_k8s_event("Unhealthy", "probe failed", "backend-a")])
    assert out == [{"type": "Warning", "reason": "Unhealthy", "message": "probe failed",
                    "object": "backend-a", "count": 1, "last_timestamp": _now()}]


def test_an_event_with_no_timestamp_falls_back_rather_than_being_dropped():
    """last_timestamp is null on an Event the apiserver has only ever seen once via
    eventTime. Dropping those loses first occurrences, which are the interesting ones."""
    from app.system_events import adapt_k8s_events

    ev = _k8s_event("OOMKilling", "out of memory", "litellm-a")
    ev.last_timestamp = None
    out = adapt_k8s_events([ev], now=_now())
    assert out[0]["last_timestamp"] == _now()


def test_restart_counts_are_summed_across_containers():
    """A pod with a sidecar restarts as a pod. Reading only the first container's
    counter — which the Services page does — would miss a sidecar crash loop."""
    from app.system_events import adapt_pod_restarts

    pod = _Obj(metadata=_Obj(name="backend-a"),
               status=_Obj(container_statuses=[_Obj(restart_count=2), _Obj(restart_count=5)]))
    assert adapt_pod_restarts([pod]) == {"backend-a": 7}


def test_a_pod_with_no_container_status_counts_as_zero():
    from app.system_events import adapt_pod_restarts

    pod = _Obj(metadata=_Obj(name="pending-a"), status=_Obj(container_statuses=None))
    assert adapt_pod_restarts([pod]) == {"pending-a": 0}


def test_boot_time_is_derived_from_host_uptime():
    """/proc/uptime is not namespaced, so inside the pod it reports the node's uptime.
    That is the only reason a container can answer "when did this node restart"."""
    from app.system_events import boot_time_from_uptime

    assert boot_time_from_uptime("17520.42 65000.00", _now()) == _now() - timedelta(seconds=17520.42)


def test_unreadable_uptime_yields_no_boot_time_rather_than_a_wrong_one():
    from app.system_events import boot_time_from_uptime

    assert boot_time_from_uptime("", _now()) is None
    assert boot_time_from_uptime("not-a-number", _now()) is None


def test_the_upsert_matches_merge_repeat():
    """The SQL and the pure function encode the same rule — neither counter moves
    backwards — and must not drift apart. A divergence would make a condition that is
    still firing look like it had stopped."""
    from app.system_events import _UPSERT

    assert "GREATEST(system_events.last_seen, EXCLUDED.last_seen)" in _UPSERT
    assert "GREATEST(system_events.occurrences, EXCLUDED.occurrences)" in _UPSERT
    assert "first_seen" not in _UPSERT.split("DO UPDATE SET")[1]


# ── filter building ───────────────────────────────────────────────────────────
# Placeholder numbering is positional, and getting it wrong does not raise — it binds
# the wrong value to the wrong column, which reads as "no events matched".

def test_the_window_alone_binds_one_parameter():
    from app.system_events import build_filters

    where, args = build_filters(hours=168)
    assert args == ["168"]
    assert where == "last_seen >= now() - ($1 || ' hours')::interval"


def test_each_filter_takes_the_next_placeholder_in_order():
    from app.system_events import build_filters

    where, args = build_filters(hours=24, severity="critical", kind="oom_kill")
    assert args == ["24", "critical", "oom_kill"]
    assert "severity = $2" in where
    assert "kind = $3" in where


def test_a_skipped_filter_does_not_leave_a_hole_in_the_numbering():
    """kind is absent, so source must be $2 and not $3."""
    from app.system_events import build_filters

    where, args = build_filters(hours=24, source="node")
    assert args == ["24", "node"]
    assert "source = $2" in where


def test_empty_strings_are_not_filters():
    from app.system_events import build_filters

    _where, args = build_filters(hours=24, severity="", kind=None)
    assert args == ["24"]
