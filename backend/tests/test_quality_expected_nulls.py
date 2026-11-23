from app.api import quality


def _check():
    return {"source_table": "orders", "overall_status": "alert", "row_change_status": "ok",
            "null_checks": {"shipped_at": {"null_count": 999, "null_rate": 99.9, "status": "alert"},
                            "note": {"null_count": 40, "null_rate": 40.0, "status": "warning"},
                            "id": {"null_count": 0, "null_rate": 0.0, "status": "ok"}},
            "warnings": [{"type": "high_null_rate", "message": "Column 'shipped_at' has 99.9% null values", "severity": "alert"},
                         {"type": "high_null_rate", "message": "Column 'note' has 40.0% null values", "severity": "warning"}]}


def test_expected_column_stops_warning_and_lowers_overall():
    out = quality.with_expected(_check(), ["shipped_at"])
    assert out["null_checks"]["shipped_at"]["status"] == "expected"
    assert [w["column"] for w in out["warnings"]] == ["note"]
    assert out["overall_status"] == "warning"
    assert out["expected_null_columns"] == ["shipped_at"]


def test_all_expected_is_ok_and_row_anomaly_stays():
    c = _check()
    c["warnings"].append({"type": "row_count_anomaly", "message": "x", "severity": "warning"})
    out = quality.with_expected(c, ["SHIPPED_AT", "note"])
    assert out["overall_status"] == "warning" and out["warnings"][0]["type"] == "row_count_anomaly"
    out = quality.with_expected(_check(), ["shipped_at", "note"])
    assert out["overall_status"] == "ok" and out["warnings"] == []


def test_unmarked_column_warns_again():
    c = quality.with_expected(_check(), ["shipped_at"])
    again = quality.with_expected(c, [])
    assert again["null_checks"]["shipped_at"]["status"] == "alert" and again["overall_status"] == "alert"


def test_spellings_and_key():
    assert quality.spellings("public.orders") == ["public.orders", "orders"]
    assert quality.spellings("orders") == ["orders"]
    assert quality.canonical("public.Orders") == quality.canonical("orders") == "orders"


def test_null_check_skips_expected(monkeypatch):
    class Cur:
        def __init__(self): self.q = None
        def execute(self, q): self.q = q
        def fetchall(self): return [("id",), ("shipped_at",)]
        def fetchone(self): return (0, 99)
    class Conn:
        def cursor(self): return Cur()
    seen = []
    orig = Cur.execute
    def ex(self, q): seen.append(q); orig(self, q)
    monkeypatch.setattr(Cur, "execute", ex)
    monkeypatch.setattr(quality, "_trino_conn", lambda: Conn())
    out = quality._run_quality_check_sync("orders", "default", 100, None, ["shipped_at"])
    assert out["overall_status"] == "ok" and out["null_checks"]["shipped_at"]["status"] == "expected"
    assert "iceberg.default.orders" in seen[0]
