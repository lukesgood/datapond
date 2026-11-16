#!/usr/bin/env python3
"""DataPond migration assessment: a read-only scan of an AWS account's Glue catalog.

    python3 scripts/assess.py --region ap-northeast-2 --out assessment.md [--databases a,b] [--no-sizes]

Run it with the customer's (or the MSP's) AWS credentials. It only reads:
  glue:GetDatabases, glue:GetTables, glue:GetConnections   — every table's format and location
  s3:ListBucket on each table location                      — table sizes (skip with --no-sizes)
  ce:GetCostAndUsage                                        — last full month's Athena/Glue/EMR/Databricks cost (optional)
Nothing is written to the account. The report classifies every table by what moving it to
DataPond takes, lists the source databases behind Glue connections (credentials are never
read into the report), and says plainly what it could not measure.

Standard library + the AWS CLI only, so it runs on any workstation or CloudShell.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys

GIB = 2 ** 30

PATHS = {
    "iceberg": ("Register in place (catalog export, no copy)", 50, None),      # tables per day
    "parquet": ("Copy into Iceberg with Trino (CREATE TABLE AS)", None, 500),  # GiB per day
    "orc": ("Copy into Iceberg with Trino (CREATE TABLE AS)", None, 500),
    "csv": ("Copy into Iceberg with Trino (CREATE TABLE AS)", None, 200),
    "json": ("Copy into Iceberg with Trino (CREATE TABLE AS)", None, 200),
    "delta": ("Manual: rewrite to Iceberg (Delta → Iceberg tooling is on the roadmap)", None, 100),
    "view": ("Recreate the view SQL in Trino (review dialect differences)", 20, None),
    "other": ("Review by hand", 5, None),
}
ORDER = list(PATHS)


def classify(table: dict) -> str:
    if table.get("TableType") == "VIRTUAL_VIEW":
        return "view"
    p = {k.lower(): str(v).lower() for k, v in (table.get("Parameters") or {}).items()}
    if p.get("table_type") == "iceberg":
        return "iceberg"
    if p.get("table_type") == "delta" or p.get("spark.sql.sources.provider") == "delta":
        return "delta"
    sd = table.get("StorageDescriptor") or {}
    fmt = str(sd.get("InputFormat") or "").lower()
    serde = str((sd.get("SerdeInfo") or {}).get("SerializationLibrary") or "").lower()
    if "parquet" in fmt or p.get("classification") == "parquet":
        return "parquet"
    if "orc" in fmt or p.get("classification") == "orc":
        return "orc"
    if "json" in serde or p.get("classification") == "json":
        return "json"
    if "textinputformat" in fmt or p.get("classification") == "csv":
        return "csv"
    return "other"


def plan(tables: list) -> list:
    out = []
    for f in ORDER:
        group = [t for t in tables if t["format"] == f]
        if not group:
            continue
        path, per_day_tables, per_day_gib = PATHS[f]
        size = sum(t.get("bytes") or 0 for t in group)
        if per_day_tables:
            days = max(1, -(-len(group) // per_day_tables))
        else:
            days = max(1, -(-int(size / GIB) // per_day_gib)) if size else max(1, -(-len(group) // 20))
        out.append({"format": f, "tables": len(group), "bytes": size, "path": path, "days": days})
    return out


_ENGINES = {"postgresql": "postgresql", "mysql": "mysql", "sqlserver": "sqlserver", "oracle": "oracle",
            "mongodb": "mongodb", "redshift": "redshift", "mariadb": "mysql"}


def sources(conns: list) -> list:
    out = []
    for c in conns:
        url = str((c.get("ConnectionProperties") or {}).get("JDBC_CONNECTION_URL")
                  or (c.get("ConnectionProperties") or {}).get("CONNECTION_URL") or "")
        engine = next((v for k, v in _ENGINES.items() if f":{k}:" in url or url.startswith(f"{k}:")
                       or f"jdbc:{k}" in url), str(c.get("ConnectionType") or "").lower())
        out.append({"name": c.get("Name"), "engine": engine,
                    "supported": engine in ("postgresql", "mysql", "sqlserver", "oracle", "mongodb")})
    return out


def _fmt_bytes(b):
    if b is None:
        return "not measured"
    for unit, size in (("TiB", 2 ** 40), ("GiB", GIB), ("MiB", 2 ** 20), ("KiB", 2 ** 10)):
        if b >= size:
            return f"{b / size:.1f} {unit}"
    return f"{b} B"


def render(data: dict) -> str:
    tables, plan_rows = data["tables"], plan(data["tables"])
    measured = all(t.get("bytes") is not None for t in tables)
    lines = [
        "# DataPond migration assessment",
        "",
        f"Account `{data['account']}` · region `{data['region']}` · databases: {', '.join(data['databases']) or '—'} · "
        f"generated {dt.date.today().isoformat()} · read-only scan",
        "",
        "## Summary",
        "",
        f"- **{len(tables)} tables**, total size {_fmt_bytes(sum(t['bytes'] or 0 for t in tables)) if measured else 'not measured'}.",
    ]
    est = sum(p["days"] for p in plan_rows)
    lines.append(f"- **Estimated migration effort: about {est} working day(s)** for one engineer (rough, from table counts and sizes below).")
    if data["sources"]:
        sup = sum(1 for s in data["sources"] if s["supported"])
        lines.append(f"- **{len(data['sources'])} source database connection(s)**, {sup} directly supported as DataPond sources (queried and synced through Trino).")
    lines += ["", "## Migration plan", "", "| Format | Tables | Size | Path | Effort (days) |", "|---|---|---|---|---|"]
    for p in plan_rows:
        lines.append(f"| {p['format']} | {p['tables']} | {_fmt_bytes(p['bytes']) if measured else 'not measured'} | {p['path']} | {p['days']} |")
    lines += ["", "## Monthly cost", ""]
    costs = data.get("costs")
    if costs:
        lines += ["| Service | Last full month (USD) |", "|---|---|"] + \
                 [f"| {k} | {v:,.2f} |" for k, v in costs.items()] + \
                 ["", f"Current total for these services: **${sum(costs.values()):,.2f}**."]
    else:
        lines.append("Cost Explorer was not readable with these credentials (it needs `ce:GetCostAndUsage`, usually "
                     "on the payer account), so current costs are **not measured**. Fill in from the bill:")
        lines += ["", "| Service | Last full month (USD) |", "|---|---|", "| Amazon Athena | |", "| AWS Glue | |",
                  "| Databricks / EMR | |", "| Other (Lambda, Step Functions) | |"]
    lines += ["",
              "DataPond on the AWS reference (one EC2 node on weekdays + Aurora Serverless v2 at 0.5 ACU + S3): "
              "about **$100–150/month** of infrastructure at small scale (measured on the reference, Nov 2026); "
              "license and support are quoted separately. Larger data or always-on use costs more.",
              "", "## Source databases", ""]
    if data["sources"]:
        lines += ["| Glue connection | Engine | DataPond source |", "|---|---|---|"] + \
                 [f"| {s['name']} | {s['engine']} | {'yes (Trino catalog)' if s['supported'] else 'not directly — review'} |"
                  for s in data["sources"]]
    else:
        lines.append("No Glue connections found. Source databases are listed during the PoC.")
    lines += ["", "## Tables", "", "| Database | Table | Format | Size |", "|---|---|---|---|"] + \
             [f"| {t['database']} | {t['name']} | {t['format']} | {_fmt_bytes(t.get('bytes'))} |" for t in tables]
    lines += ["", "## What this scan did not cover", "",
              "- Query patterns and concurrency (dashboards, scheduled jobs) — measured in a side-by-side PoC.",
              "- Spark jobs, notebooks and ML pipelines — DataPond runs SQL; Spark and Jupyter are optional add-ons.",
              "- Permissions in Lake Formation or IAM — re-created as DataPond catalog grants and row/column policies.",
              "- Data quality and schema drift inside the tables."]
    return "\n".join(lines) + "\n"


def _aws(args, region):
    r = subprocess.run(["aws", *args, "--region", region, "--output", "json"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return json.loads(r.stdout or "{}")


def _size(location, region):
    if not location.startswith("s3://"):
        return None
    bucket, _, prefix = location[5:].partition("/")
    try:
        r = _aws(["s3api", "list-objects-v2", "--bucket", bucket, "--prefix", prefix.rstrip("/") + "/",
                  "--query", "sum(Contents[].Size)"], region)
        return int(r or 0)
    except Exception:
        return None


def _costs(region):
    end = dt.date.today().replace(day=1)
    start = (end - dt.timedelta(days=1)).replace(day=1)
    r = _aws(["ce", "get-cost-and-usage", "--time-period", f"Start={start},End={end}", "--granularity", "MONTHLY",
              "--metrics", "UnblendedCost", "--group-by", "Type=DIMENSION,Key=SERVICE"], "us-east-1")
    out = {}
    for g in r["ResultsByTime"][0]["Groups"]:
        name = g["Keys"][0]
        if any(k in name for k in ("Athena", "Glue", "Elastic MapReduce", "Databricks", "Lambda", "Step Functions")):
            out[name] = float(g["Metrics"]["UnblendedCost"]["Amount"])
    return out


def scan(region, databases=None, sizes=True):
    account = _aws(["sts", "get-caller-identity"], region)["Account"]
    dbs = [d["Name"] for d in _aws(["glue", "get-databases"], region)["DatabaseList"]]
    if databases:
        dbs = [d for d in dbs if d in databases]
    tables = []
    for db in dbs:
        for tb in _aws(["glue", "get-tables", "--database-name", db], region)["TableList"]:
            loc = (tb.get("StorageDescriptor") or {}).get("Location") or ""
            tables.append({"database": db, "name": tb["Name"], "format": classify(tb),
                           "bytes": _size(loc, region) if sizes else None})
    try:
        conns = _aws(["glue", "get-connections", "--hide-password"], region)["ConnectionList"]
    except Exception:
        conns = []
    try:
        costs = _costs(region)
    except Exception:
        costs = None
    return {"account": account, "region": region, "databases": dbs, "tables": tables,
            "sources": sources(conns), "costs": costs}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--region", required=True)
    ap.add_argument("--databases", help="comma-separated Glue databases (default: all)")
    ap.add_argument("--no-sizes", action="store_true", help="skip S3 size listing")
    ap.add_argument("--out", default="-", help="Markdown file (default: stdout)")
    args = ap.parse_args(argv)
    data = scan(args.region, args.databases.split(",") if args.databases else None, sizes=not args.no_sizes)
    md = render(data)
    if args.out == "-":
        sys.stdout.write(md)
    else:
        open(args.out, "w").write(md)
        print(f"wrote {args.out}: {len(data['tables'])} tables", file=sys.stderr)


if __name__ == "__main__":
    main()
