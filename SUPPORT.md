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
access control, PII handling, audit and spend — and the **AWS Single-Node Reference**
that runs it.

The optional OSS add-ons (Trino, Airflow, Spark, Polaris, RisingWave, OpenMetadata,
Jupyter, MLflow) are configuration around upstream projects. We will help with how the
chart wires them; we are not in a position to support those projects themselves.

Declarative pipelines compile to placeholder tasks and refuse to deploy for that
reason. They are not a supported feature — see `docs/PRODUCTIZATION_READINESS_ASSESSMENT.md`
P0-1.

## Enterprise

`ee/LICENSE` is a placeholder awaiting legal review, and nothing under `ee/` is offered
for sale. Enterprise features present in the image are a preview: usable, and not
covered by any commercial agreement, because no such agreement exists yet.
