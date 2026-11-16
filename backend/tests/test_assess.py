"""Migration assessment (demand validation action 1): a read-only scan of a customer's Glue
catalog that classifies every table by what moving it to DataPond takes."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("assess", Path(__file__).resolve().parents[2] / "scripts/assess.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def t(**kw):
    base = {"Name": "x", "TableType": "EXTERNAL_TABLE", "Parameters": {}, "StorageDescriptor": {"Location": "s3://b/x"}}
    base.update(kw)
    return base


def test_tables_are_classified_by_what_moving_them_takes():
    assert a.classify(t(Parameters={"table_type": "ICEBERG"})) == "iceberg"
    assert a.classify(t(Parameters={"spark.sql.sources.provider": "delta"})) == "delta"
    assert a.classify(t(Parameters={"table_type": "DELTA"})) == "delta"
    pq = {"Location": "s3://b/x", "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"}
    assert a.classify(t(StorageDescriptor=pq)) == "parquet"
    orc = {"Location": "s3://b/x", "InputFormat": "org.apache.hadoop.hive.ql.io.orc.OrcInputFormat"}
    assert a.classify(t(StorageDescriptor=orc)) == "orc"
    csv = {"Location": "s3://b/x", "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
           "SerdeInfo": {"SerializationLibrary": "org.openx.data.jsonserde.JsonSerDe"}}
    assert a.classify(t(StorageDescriptor=csv)) == "json"
    txt = {"Location": "s3://b/x", "InputFormat": "org.apache.hadoop.mapred.TextInputFormat"}
    assert a.classify(t(StorageDescriptor=txt)) == "csv"
    assert a.classify(t(TableType="VIRTUAL_VIEW")) == "view"


def test_the_plan_groups_tables_with_a_path_and_an_effort():
    tables = [{"format": "iceberg", "bytes": 10 * 2**30}] * 30 + [{"format": "parquet", "bytes": 2**40}] + \
             [{"format": "delta", "bytes": 2**30}] * 2 + [{"format": "view", "bytes": 0}]
    plan = {p["format"]: p for p in a.plan(tables)}
    assert plan["iceberg"]["path"].startswith("Register in place") and plan["iceberg"]["days"] == 1
    assert plan["parquet"]["path"].startswith("Copy into Iceberg") and plan["parquet"]["days"] >= 1
    assert plan["delta"]["path"].startswith("Manual") and plan["delta"]["tables"] == 2
    assert plan["view"]["path"].startswith("Recreate")


def test_sources_come_from_glue_connections_without_credentials():
    conns = [{"Name": "mes", "ConnectionType": "JDBC",
              "ConnectionProperties": {"JDBC_CONNECTION_URL": "jdbc:oracle:thin:@//mes.corp:1521/MES", "PASSWORD": "secret"}},
             {"Name": "shop", "ConnectionType": "JDBC",
              "ConnectionProperties": {"JDBC_CONNECTION_URL": "jdbc:mysql://shop.cluster.rds.amazonaws.com:3306/shop"}}]
    s = a.sources(conns)
    assert [(x["name"], x["engine"], x["supported"]) for x in s] == [("mes", "oracle", True), ("shop", "mysql", True)]
    assert "secret" not in str(s)


def test_the_report_names_what_was_not_measured():
    r = a.render({"account": "123456789012", "region": "us-east-1", "databases": ["default"],
                  "tables": [{"database": "default", "name": "orders", "format": "iceberg", "bytes": None}],
                  "sources": [], "costs": None})
    assert "# DataPond migration assessment" in r and "orders" not in r.split("## Tables")[0]
    assert "not measured" in r and "Cost Explorer" in r
