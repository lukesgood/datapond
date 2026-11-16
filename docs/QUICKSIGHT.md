# Amazon QuickSight with DataPond

Three of six personas in the demand validation asked how their existing QuickSight
dashboards keep working (`DEMAND_VALIDATION_PERSONAS_2026-11.md`). There are two paths. They
differ in what governs the data on the way to QuickSight.

| | A. QuickSight → Athena → Glue tables | B. QuickSight → Trino (direct connector) |
|---|---|---|
| Works on the reference today | **Yes** (verified 2026-11-16) | No — needs Trino exposed with TLS and authentication |
| Tables it sees | Glue-catalog tables only (not Polaris) | Every catalog Trino serves (Glue, Polaris, live source DBs) |
| PII | Already masked in the lake at sync time | Same for lake tables; live source tables are **not** masked |
| DataPond catalog grants, row filters, masks | **Do not apply** (Athena uses IAM / Lake Formation) | Apply only with Trino Layer 2 (file-based access control) |
| Cost | Athena per TB scanned, or SPICE imports | Runs on the DataPond node |
| DataPond audit trail | No | Trino query log only |

## A. Through Athena (works today)

DataPond writes Iceberg tables and registers them in the Glue catalog, and Athena engine v3
reads those tables directly. Verified on the reference on 2026-11-16: `SELECT count(*) …
FROM default.customers` in Athena returned the 1,200 rows DataPond synced, with every email
already masked.

1. In QuickSight, **Datasets → New dataset → Athena**, pick the workgroup (`primary` or one
   you create for BI), then the Glue database (e.g. `default`) and the table, or write
   custom SQL.
2. Prefer **SPICE** (import on a schedule) over direct query: dashboards stop scanning S3 on
   every view, and Athena cost becomes one scan per refresh.
3. Permissions for QuickSight's service role: Athena on the workgroup; Glue read on the
   databases; S3 read on the DataPond data bucket and read/write on the Athena results
   location; KMS decrypt if the bucket uses a customer key.

**What to know.** The data is already masked where DataPond masks it (each synced table's
PII columns), but DataPond's **catalog grants, row filters and column masks are not in this
path**. Anyone QuickSight lets see the dataset sees every row. Restrict it with QuickSight
dataset permissions and row-level security, or with Lake Formation. Polaris tables are not
visible to Athena. If a table must reach QuickSight, keep it in the Glue catalog: give it
Glue as its sync target, or keep a Glue mirror. A mirror is read-only and kept current by
DataPond (`PORTABILITY.md`).

## B. Directly to Trino (not yet on the reference)

QuickSight has a native Trino connector and can reach Trino inside a VPC through a QuickSight
VPC connection ([AWS docs](https://docs.aws.amazon.com/quicksight/latest/user/connecting-to-trino.html),
[supported VPC sources](https://docs.aws.amazon.com/quicksight/latest/user/vpc-connection-supported-data-sources.html)).
On the reference, Trino serves only the cluster: it has no TLS, no user authentication,
and no Service outside the cluster. Using this path would need:

- Trino with HTTPS and password (or JWT) authentication. Trino accepts passwords only over
  HTTPS.
- A network path from the QuickSight VPC connection to Trino, such as an internal load
  balancer, and a DNS name QuickSight can resolve.
- **Trino Layer 2 on** (`trino.rls.enabled`), so DataPond's row filters and masks are
  applied inside the engine for that QuickSight user. Live source catalogs (`src_*`) are not
  masked by Layer 2 in the same way as synced tables. Expose only lake catalogs to BI.

The chart does not configure any of this today; it is on the roadmap. Until then, use path
A.

## Which to use

- Dashboards on synced lake tables in the Glue catalog: **path A with SPICE**, plus QuickSight
  or Lake Formation row-level security where row filtering matters.
- Dashboards that need Polaris tables, live sources, or DataPond's own row policies: wait
  for path B, or use DataPond's **Analytics** dashboards, where every policy applies.
