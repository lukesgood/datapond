# Security

## Reporting a vulnerability

Email **security@datapond.io** with enough detail to reproduce: the version or commit,
the deployment profile, and the request or configuration that triggers it. If you have
a proof of concept, include it — a report that cannot be reproduced usually cannot be
fixed either.

Please do not open a public issue for a suspected vulnerability. Please do not test
against a deployment you do not operate.

**What to expect.** Acknowledgement within 3 working days. An initial assessment —
whether it reproduces, and what we think the severity is — within 10 working days.
After that, progress on the same channel until it closes.

We do not currently offer a bounty. If you would like credit in the fix's release
notes, say so and we will include it.

## Severity

| | |
|---|---|
| **Critical** | Unauthenticated access to data or the ability to run code as the deployment |
| **High** | Authenticated escalation past a role, or exposure of another tenant's data |
| **Medium** | Exposure limited to metadata, or requiring an unusual configuration |
| **Low** | Hardening gaps with no demonstrated path to impact |

These describe how we triage. They are not a service level: see SUPPORT.md.

## Scope

In scope: the backend and frontend in this repository, the Helm chart, and the
Terraform in `terraform/`.

Out of scope: the third-party components a profile can enable (Trino, Airflow, Spark,
Polaris, RisingWave, OpenMetadata, MinIO, Ollama), which have their own projects and
their own disclosure processes; and findings that depend on a deployment ignoring the
documented configuration, such as running with a default credential the chart tells
you to change.

## What this product does and does not protect

Stated plainly, because a security policy that implies more than the code does is
worse than none.

**It does.** Authentication with roles enforced at every mutating route; PII masking
at ingest and again on retrieval; per-user attribution of model spend; an audit log of
authentication events; row-level security and column masking for query paths that go
through the SQL rewrite engine.

**It does not, yet.** `docs/PRODUCTIZATION_READINESS_ASSESSMENT.md` is the current,
unedited list of what is missing, including which items block a production release.
Read it before deciding what this deployment may hold. In particular: the audit log is
not append-only, database migrations are not versioned, and row-level security is not
enforced on data paths that reach storage directly rather than through the query
engine.
