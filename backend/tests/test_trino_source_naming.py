"""A Trino-backed connection is a Trino catalog named from the connection, whose catalog
file carries the password only as an environment reference (Review Focus 1 and 2 of the
Phase 2 plan)."""
import re

import pytest

from app.connectors.base import ConnectorType as T
from app.connectors import trino_source as ts


def test_the_five_types_run_on_trino_and_the_rest_do_not():
    assert {t for t in T if ts.engine_of(t) == "trino"} == {
        T.POSTGRESQL, T.MYSQL, T.SQLSERVER, T.ORACLE, T.MONGODB, T.DATABASE_URL}
    assert ts.engine_of(T.REST_API) == "python" and ts.engine_of(T.S3) == "python"


@pytest.mark.parametrize("name,expected", [
    ("Sales DB", "src_sales_db"), ("sales-db", "src_sales_db"), ("SALES db", "src_sales_db"),
    ("Sample E-Commerce DB", "src_sample_e_commerce_db"),
    ("  weird__name!! ", "src_weird_name"),
])
def test_slug_is_lowercase_ascii_with_underscores(name, expected):
    assert ts.source_slug(name) == expected


def test_slug_fits_32_characters_for_a_long_korean_name():
    s = ts.source_slug("영업본부 고객관리 운영 데이터베이스 2026 " * 2 + "crm")
    assert re.fullmatch(r"src_[a-z0-9_]{1,28}", s), s


def test_a_name_without_ascii_still_yields_a_catalog_name():
    s = ts.source_slug("고객관리")
    assert len(s) == 12 and s.startswith("src_")


def test_unique_slug_suffixes_on_a_clash_case_insensitively():
    assert ts.unique_slug("src_sales_db", {"SRC_SALES_DB"}) == "src_sales_db_2"
    assert ts.unique_slug("src_sales_db", {"src_sales_db", "src_sales_db_2"}) == "src_sales_db_3"
    long = "src_" + "a" * 28
    assert len(ts.unique_slug(long, {long})) <= 32


def test_credential_env_name():
    assert ts.credential_env("src_sales_db") == "SRC_SALES_DB_PASSWORD"


PG = {"host": "db.internal", "port": 5432, "database": "crm", "username": "ro",
      "password": "p;a&s%s@w#o'r\"d x", "ssl": True}


def test_postgresql_catalog_file_carries_the_password_only_as_an_env_reference():
    text = ts.render_catalog_properties(T.POSTGRESQL, "src_crm", PG)
    assert text.splitlines() == [
        "connector.name=postgresql",
        "connection-url=jdbc:postgresql://db.internal:5432/crm?sslmode=require",
        "connection-user=ro",
        "connection-password=${ENV:SRC_CRM_PASSWORD}",
    ]
    assert text.endswith("\n")
    assert PG["password"] not in text and "p;a" not in text


def test_mongodb_url_encodes_the_user_and_keeps_the_password_in_env():
    cfg = {**PG, "port": 27017, "username": "r@o", "auth_source": "admin"}
    text = ts.render_catalog_properties(T.MONGODB, "src_m", cfg)
    assert ("mongodb.connection-url=mongodb://r%40o:${ENV:SRC_M_PASSWORD}@db.internal:27017/crm"
            "?authSource=admin&tls=true") in text
    assert ts.credential_value(T.MONGODB, cfg) == "p%3Ba%26s%25s%40w%23o%27r%22d+x"
    assert ts.credential_value(T.POSTGRESQL, PG) == PG["password"]


def test_oracle_pins_number_scale_and_sqlserver_names_the_database():
    assert "oracle.number.default-scale=10" in ts.render_catalog_properties(T.ORACLE, "src_o", PG)
    assert ("jdbc:sqlserver://db.internal:5432;databaseName=crm;encrypt=true;"
            "trustServerCertificate=true") in ts.render_catalog_properties(T.SQLSERVER, "src_s", PG)


def test_mysql_has_no_database_in_the_url_and_ssl_is_opt_in():
    text = ts.render_catalog_properties(T.MYSQL, "src_my", {**PG, "ssl": False, "database": ""})
    assert "connection-url=jdbc:mysql://db.internal:5432\n" in text
    assert "sslMode=REQUIRED" in ts.render_catalog_properties(T.MYSQL, "src_my", {**PG, "database": ""})


@pytest.mark.parametrize("field", ["host", "database", "username"])
def test_a_value_that_could_inject_a_property_line_is_refused(field):
    with pytest.raises(ValueError):
        ts.render_catalog_properties(T.POSTGRESQL, "src_x", {**PG, field: "a\nconnector.name=memory"})


def test_a_python_type_has_no_catalog_file():
    with pytest.raises(ValueError):
        ts.render_catalog_properties(T.REST_API, "src_x", PG)


def test_database_url_normalises_to_postgresql_or_mysql():
    t, cfg = ts.normalise_type_and_config(
        T.DATABASE_URL, {"database_url": "postgresql://u:p%40ss@h:5433/fin"})
    assert t == T.POSTGRESQL and cfg == {"host": "h", "port": 5433, "database": "fin",
                                         "username": "u", "password": "p@ss", "ssl": False}
    t, cfg = ts.normalise_type_and_config(T.DATABASE_URL, {"database_url": "mysql+pymysql://u:p@h/db"})
    assert t == T.MYSQL and cfg["port"] == 3306
    with pytest.raises(ValueError):
        ts.normalise_type_and_config(T.DATABASE_URL, {"database_url": "mssql+pyodbc://u:p@h/db"})


def test_other_types_pass_through_with_port_coerced():
    t, cfg = ts.normalise_type_and_config(T.POSTGRESQL, {**PG, "port": "5432", "name": "x"})
    assert t == T.POSTGRESQL and cfg["port"] == 5432 and cfg["name"] == "x"
