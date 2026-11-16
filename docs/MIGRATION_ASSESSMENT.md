# Migration assessment — `scripts/assess.py`

A read-only scan of a customer's AWS account that answers the first two questions every
persona asked (`DEMAND_VALIDATION_PERSONAS_2026-11.md`): **what would moving take** and
**what does it cost now**. It is meant to be run by the MSP or the customer before a PoC,
and its report is the one page for an IT lead's budget meeting.

```bash
# customer's or MSP's credentials, any workstation or CloudShell with the AWS CLI
python3 scripts/assess.py --region ap-northeast-2 --out assessment.md
python3 scripts/assess.py --region ap-northeast-2 --databases sales,ops --no-sizes --out assessment.md
```

**It only reads:** `glue:GetDatabases`, `glue:GetTables`, `glue:GetConnections` (passwords
hidden), `s3:ListBucket` on table locations (for sizes; skip with `--no-sizes`), and
`ce:GetCostAndUsage` (last full month for Athena, Glue, EMR, Databricks, Lambda, Step
Functions; optional, usually only on the payer account). Nothing is written to the account.

**The report:**
- **Summary.** Table count, total size and a rough effort estimate in working days.
- **Migration plan by format.** Iceberg registers in place through the catalog export, with
  no copy. Parquet, ORC, CSV and JSON are copied into Iceberg with Trino. Delta is a manual
  rewrite for now. Views are recreated as SQL.
- **Monthly cost.** Last month's figures from Cost Explorer, or blank rows to fill in from
  the bill. The DataPond reference infrastructure range sits next to them.
- **Source databases.** Taken from Glue connections, each marked with whether DataPond reads
  it as a Trino source.
- **What the scan did not cover.** Query patterns, Spark jobs, IAM and Lake Formation rules,
  and data quality. The side-by-side PoC measures these.

Sample output, from our own reference account: [`research/assessment-sample-2026-11.md`](research/assessment-sample-2026-11.md)
(25 Iceberg tables → "register in place, about 1 day"; Cost Explorer not readable with those
credentials, so the cost rows are blank). The effort figures are rough planning numbers, not
a quote.
