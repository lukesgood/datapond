"""The console asks /governance/stats for the query count alone.

Counting today's queries is one COUNT; the PII scan walks the catalog table by table
and took 7 s uncached on the live node, holding "Queries today" blank the whole time
while /governance/pii-report ran the same scan in parallel.
"""
from app.api import governance as g


class _Q:
    def filter(self, *a):
        return self

    def scalar(self):
        return 3


class _Db:
    def query(self, *a):
        return _Q()


def test_include_pii_false_skips_the_scan(monkeypatch):
    def _boom():
        raise AssertionError("scanned although include_pii=false")
    monkeypatch.setattr(g, "_scan_pii_tables", _boom)
    r = g.get_governance_stats(_Db(), include_pii=False)
    assert r.queries_today == 3 and r.pii_detections is None


def test_default_still_counts_pii(monkeypatch):
    class _T:
        pii_columns = ["email", "phone"]
    monkeypatch.setattr(g, "_scan_pii_tables", lambda: [_T(), _T()])
    r = g.get_governance_stats(_Db(), include_pii=True)
    assert r.pii_detections == 4
