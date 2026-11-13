# Support

## What is available today

**Best effort, and no SLA.** There is no paid support contract, no guaranteed response
time, and no on-call rotation. Saying otherwise would be the easiest sentence to write
here and the one that would cost someone the most.

- **Questions and bugs** — GitHub issues on this repository.
- **Security** — see SECURITY.md. Do not use a public issue.

Issues are read on working days, Asia/Seoul. Something clearly broken in the Portable
Core path gets looked at sooner than a question about an optional add-on.

## What helps us help you

- The commit or image tag (`Settings → Overview` shows the running version).
- The profile — which `values-*.yaml`, and what you overrode.
- `GET /api/health/ready`, which reports whether each bootstrap succeeded and whether
  the database is reachable.
- What you expected, what happened, and the smallest way to reproduce it.

Please redact credentials before pasting logs. `ENCRYPTION_KEY`, `JWT_SECRET`,
`INTERNAL_API_KEY` and provider keys appear in environment dumps.

## Versions

There is no long-term support branch and no backporting. Fixes land on `main` and ship
in the next image; upgrading is the way to receive one.

`docs/UPGRADING.md` records every change that alters behaviour for an existing
deployment — read it before upgrading, particularly the entries about roles, which
narrowed what non-admin accounts can do.

## Supported scope

The **Portable Core** path — ingest, embed, retrieve, rerank, cited answers, plus
access control, PII handling, audit and spend — on the two starters that run it:
the **AWS Single-Node Reference** / `values-foundation.yaml`, and the self-hosted
**Sovereign Core** (`values-sovereign-core.yaml`: in-cluster MinIO and Ollama;
installed from nothing on every CI run — MinIO, Ollama, local-only egress, and an
embed → ingest → search round trip; a long-running self-hosted acceptance remains open).

**Trino as the query engine** (SQL Lab, catalog preview, dashboards, metrics) on every
profile, the AWS Single-Node Reference included, where it runs in-cluster over the Glue
catalog (2.4; Amazon Athena is no longer used). We support Trino as the chart configures
it: one coordinator, the `iceberg` catalog, the file-based access control the backend
writes. Trino clusters, catalogs or settings outside that configuration are upstream
Trino, not DataPond.

**Database sources through Trino's connectors** (2.5): PostgreSQL, MySQL, SQL Server,
Oracle and MongoDB connections are Trino catalogs, synced by Trino SQL, as Trino 482's
connectors expose them. PostgreSQL is exercised end to end on every CI run (a source
registered, the engine restarted, a sync, a federated query, the catalog ACL). MySQL,
SQL Server, Oracle and MongoDB are verified by unit tests and the pre-create connection
probe only — there is no live acceptance for them yet; a type-mapping or dialect issue
there is a bug we want to hear about, not a configuration we can promise. The SQLAlchemy
URL type and the pandas sync path are gone.

**Iceberg catalogs** (2.6–2.7): Glue, and Polaris as the chart deploys it (in-cluster, its
metadata in the deployment's PostgreSQL/Aurora; beside Glue on the AWS reference since
2026-11-12), plus other Iceberg REST catalogs registered under Settings → Data catalogs. The
catalog export and the one-writer-per-table guards (`docs/PORTABILITY.md`) are supported for
those catalogs; writes made to a mirror by an engine outside DataPond are detected, not
prevented.

The other optional OSS add-ons (Airflow, Spark, RisingWave, OpenMetadata, Jupyter,
MLflow) are configuration around upstream projects. We will help with how the chart
wires them; we are not in a position to support those projects themselves.

### Add-ons this release does not support

<!-- unsupported-addons -->
- Airflow
- Spark
- Polaris
- RisingWave
- OpenMetadata
- Jupyter
- MLflow
<!-- /unsupported-addons -->

Declarative pipelines compile to placeholder tasks and refuse to deploy for that
reason. They are not a supported feature — see `docs/PRODUCTIZATION_READINESS_ASSESSMENT.md`
P0-1.

## Enterprise

`ee/LICENSE` is a placeholder awaiting legal review, and nothing under `ee/` is offered
for sale. Enterprise features present in the image are a preview: usable, and not
covered by any commercial agreement, because no such agreement exists yet.
