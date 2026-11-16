# DataPond migration assessment

Account `588738574974` · region `us-east-1` · databases: default, public, raw, refined, serving · generated 2026-11-16 · read-only scan

## Summary

- **25 tables**, total size not measured.
- **Estimated migration effort: about 1 working day(s)** for one engineer (rough, from table counts and sizes below).

## Migration plan

| Format | Tables | Size | Path | Effort (days) |
|---|---|---|---|---|
| iceberg | 25 | not measured | Register in place (catalog export, no copy) | 1 |

## Monthly cost

Cost Explorer was not readable with these credentials (it needs `ce:GetCostAndUsage`, usually on the payer account), so current costs are **not measured**. Fill in from the bill:

| Service | Last full month (USD) |
|---|---|
| Amazon Athena | |
| AWS Glue | |
| Databricks / EMR | |
| Other (Lambda, Step Functions) | |

DataPond on the AWS reference (one EC2 node on weekdays + Aurora Serverless v2 at 0.5 ACU + S3): about **$100–150/month** of infrastructure at small scale (measured on the reference, Nov 2026); license and support are quoted separately. Larger data or always-on use costs more.

## Source databases

No Glue connections found. Source databases are listed during the PoC.

## Tables

| Database | Table | Format | Size |
|---|---|---|---|
| default | agents | iceberg | not measured |
| default | api_events | iceberg | not measured |
| default | business_calendar | iceberg | not measured |
| default | campaign_touches | iceberg | not measured |
| default | campaigns | iceberg | not measured |
| default | carrier_scans | iceberg | not measured |
| default | customers | iceberg | not measured |
| default | fx_rates | iceberg | not measured |
| default | inventory | iceberg | not measured |
| default | invoices | iceberg | not measured |
| default | knowledge_articles | iceberg | not measured |
| default | order_items | iceberg | not measured |
| default | orders | iceberg | not measured |
| default | page_events | iceberg | not measured |
| default | payments | iceberg | not measured |
| default | product_returns | iceberg | not measured |
| default | products | iceberg | not measured |
| default | service_metrics | iceberg | not measured |
| default | shipments | iceberg | not measured |
| default | support_tickets | iceberg | not measured |
| default | ticket_messages | iceberg | not measured |
| default | warehouse_sensors | iceberg | not measured |
| default | warehouses | iceberg | not measured |
| public | invoices | iceberg | not measured |
| public | payments | iceberg | not measured |

## What this scan did not cover

- Query patterns and concurrency (dashboards, scheduled jobs) — measured in a side-by-side PoC.
- Spark jobs, notebooks and ML pipelines — DataPond runs SQL; Spark and Jupyter are optional add-ons.
- Permissions in Lake Formation or IAM — re-created as DataPond catalog grants and row/column policies.
- Data quality and schema drift inside the tables.
