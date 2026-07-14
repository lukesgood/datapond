"""Query-engine abstraction. Selected by QUERY_ENGINE (athena|trino, default trino).
Isolates dialect, execution, and error-mapping so queries.py / ai_sql.py / rls stay
engine-agnostic. TrinoEngine wraps the existing self-hosted path; AthenaEngine uses
pyathena (serverless, AWS-native)."""
import os


def _clean_trino_msg(msg: str) -> str:
    if 'message="' in msg:
        try:
            return msg.split('message="')[1].split('"')[0]
        except Exception:
            return msg
    return msg


class TrinoEngine:
    default_catalog = "iceberg"
    default_schema = "default"
    rls_dialect = "trino"
    ai_dialect_prompt = "The query engine is Trino. Tables are Apache Iceberg format."
    ai_table_prefix = "iceberg"

    def execute(self, sql, user):
        from app.api.queries import get_trino_connection
        conn = get_trino_connection(user)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        cur.close(); conn.close()
        return rows, cols

    def map_error(self, exc):
        msg = str(exc)
        clean = _clean_trino_msg(msg)
        low = msg.lower()
        if "SYNTAX_ERROR" in msg or "syntax error" in low:
            return "error", f"Syntax error: {clean}", 400
        if "TABLE_NOT_FOUND" in msg or ("table" in low and "not found" in low):
            return "error", f"Table not found: {clean}", 400
        if "SCHEMA_NOT_FOUND" in msg or ("schema" in low and "not found" in low):
            return "error", f"Schema not found: {clean}", 400
        if "CATALOG_NOT_FOUND" in msg:
            return "error", f"Catalog not found: {clean}", 400
        if "PERMISSION_DENIED" in msg:
            return "error", f"Permission denied: {clean}", 403
        if "timeout" in low:
            return "timeout", "Query timed out (30s limit). Try adding a LIMIT clause.", 504
        if "connect" in low or "connection" in low:
            return "error", "Cannot connect to query engine. Check if Trino is running.", 400
        return "error", clean if clean != msg else f"Query failed: {clean}", 400


class AthenaEngine:
    default_catalog = "AwsDataCatalog"
    rls_dialect = "athena"
    ai_dialect_prompt = ("The query engine is Amazon Athena (Trino/Presto SQL, engine v3). "
                         "Tables are Apache Iceberg registered in AWS Glue.")
    ai_table_prefix = "AwsDataCatalog"

    @property
    def default_schema(self):
        return os.getenv("ATHENA_DATABASE", "default")

    def execute(self, sql, user):
        from pyathena import connect
        conn = connect(
            s3_staging_dir=os.getenv("ATHENA_OUTPUT_LOCATION", ""),
            region_name=os.getenv("S3_REGION", "us-east-1"),
            work_group=os.getenv("ATHENA_WORKGROUP", "primary"),
            schema_name=os.getenv("ATHENA_DATABASE", "default"),
            catalog_name="AwsDataCatalog",
        )
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        cur.close(); conn.close()
        return rows, cols

    def map_error(self, exc):
        msg = str(exc)
        low = msg.lower()
        if "accessdenied" in low or "not authorized" in low:
            return "error", f"Access denied: {msg[:300]}", 403
        if "syntax_error" in low or "cannot be resolved" in low or "mismatched input" in low:
            return "error", f"Syntax error: {msg[:300]}", 400
        if "table_not_found" in low or ("does not exist" in low and "table" in low):
            return "error", f"Table not found: {msg[:300]}", 404
        if "schema_not_found" in low or "database does not exist" in low:
            return "error", f"Schema not found: {msg[:300]}", 400
        if "timeout" in low or "timed out" in low:
            return "timeout", "Query timed out. Try adding a LIMIT clause or narrowing the scan.", 504
        if "outputlocation" in low or ("s3" in low and "staging" in low):
            return "error", "Athena result location not configured (ATHENA_OUTPUT_LOCATION).", 400
        return "error", f"Query failed: {msg[:300]}", 400


def get_engine():
    backend = os.getenv("QUERY_ENGINE", "trino").strip().lower()
    return AthenaEngine() if backend == "athena" else TrinoEngine()
