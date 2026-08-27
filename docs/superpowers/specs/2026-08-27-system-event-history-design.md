# System Event History

A durable record of infrastructure state changes, under Infrastructure → Events.

## The gap

`GET /services/{service}/events` (`app/api/services.py:812`) is the only event surface
and it loses everything twice over:

1. Kubernetes Events expire — the apiserver's default TTL is one hour.
2. It queries `involvedObject.name={pod.metadata.name}` for pods that *currently
   exist*. When a pod is replaced, its events become unreachable; you cannot ask
   about the pod that died, which is the pod you wanted to ask about.

Observed on the live single node on 2026-08-27: `uptime` reported 4h52m against pods
created two days earlier with `restartCount: 7`. The node had rebooted, and the
product held no record of it — `kubectl get events` showed 27 minutes of history.

`auth_audit_log` covers authentication. `query_history` covers queries. Nothing
covers the infrastructure.

## Boundary

**Record what changed and what died. Do not record what logged.**

| Recorded | Not recorded |
|---|---|
| Pod restart, OOMKill, probe failure, image-pull failure, scheduling failure | Request logs, 5xx streams |
| Node reboot (detected after the fact, see Limits) | Pod stdout — `/services/{s}/logs` already serves it |
| Helm revision change, migration applied | Authentication — `auth_audit_log` |
| Backend start/stop, and `startup_check` returning `behind`/`ahead` | Queries — `query_history` |

Without this line the feature becomes a log store on a single node, which is not
what this product should build.

## Storage

Table `system_events`:

| Column | Purpose |
|---|---|
| `dedup_key` | stable identity of a repeating condition; unique |
| `kind` | `pod_restart`, `oom_kill`, `probe_failure`, `image_pull_failure`, `schedule_failure`, `node_reboot`, `release_change`, `migration`, `backend_lifecycle` |
| `severity` | `info` / `warning` / `critical` |
| `source` | `kubernetes`, `node`, `helm`, `backend` |
| `object` | pod, node, or release name |
| `message` | human-readable detail |
| `first_seen`, `last_seen`, `count` | a repeating condition is one row, not N |
| `details` | JSONB, provenance for anything the UI does not render |

This is the first Alembic migration on top of `0001_baseline`, which exercises the
P0-6 machinery for real. `CREATE TABLE` is not a contract violation, so
`migration_rules.py` passes it without a `Contract-of:` line.

## Collection

An in-process asyncio loop started at backend startup, single-leader via a Postgres
advisory lock — the same shape as `app/rag_scheduler.py`, with its own lock key.

**Polling, not a watch.** The backend runs two replicas and restarts on every deploy.
A watch stream needs reconnection handling and still misses the gap while it is down.
Polling with a dedup key is idempotent and gap-tolerant: re-reading the same window
writes nothing new. Kubernetes Events carry `count` and `lastTimestamp`, so the
window loses no information a watch would have caught.

**Retention** is a cutoff in days plus a row ceiling, pruned on the same tick.
Unbounded growth is not acceptable on a single node.

## Interface

`GET /api/system/events` — filterable by kind, severity, source, and since.
Permission `service:manage`, matching the page that shows it. This adds no new
permission vocabulary. `auditor` holds `audit:read` but not `service:manage`, so it
cannot see Infrastructure at all today; widening that is a separate decision.

UI: a third entry in `TABS` in `components/infra/infra-tabs.tsx`, giving
`Services | System | Events`.

## Limits, stated in the product

**Nothing is collected while the backend is down.** A node reboot is therefore
detected *after* the fact, by a discontinuity in boot time, and the cause of the
reboot is not in this table. That answer lives in CloudWatch and the EC2 console.

The reboot row says so: "node restarted at 01:48 — cause not recorded", with a link
out. Inferring a cause we did not observe would make the record worse than its
absence, because it would be believed.

## Testing

Pure functions carry the logic and are tested first: dedup key derivation, which
Kubernetes events are worth keeping, restart detection by counter delta, reboot
detection by boot-time discontinuity, merge-on-repeat semantics, and the retention
cutoff. The impure edges — the Kubernetes read, the upsert, the loop — stay thin
enough to read.
