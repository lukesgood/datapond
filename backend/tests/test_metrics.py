"""Unit tests for the CloudWatch metrics emitter (app.metrics).

app.metrics is stdlib-only (boto3 is imported lazily), so these run anywhere.
"""


def test_disabled_is_noop(monkeypatch):
    import app.metrics as m
    monkeypatch.delenv("CLOUDWATCH_METRICS_ENABLED", raising=False)
    calls = []
    monkeypatch.setattr(m._executor, "submit", lambda *a, **k: calls.append((a, k)))
    m.emit("RagQuery", 1)
    assert calls == []  # gated off: never submitted


def test_enabled_submits_with_args(monkeypatch):
    import app.metrics as m
    monkeypatch.setenv("CLOUDWATCH_METRICS_ENABLED", "true")
    calls = []
    monkeypatch.setattr(m._executor, "submit", lambda fn, *a: calls.append(a))
    m.emit("BytesScanned", 2048, "Bytes", {"Engine": "Athena"})
    assert calls == [("BytesScanned", 2048, "Bytes", {"Engine": "Athena"})]


def test_put_formats_datum(monkeypatch):
    import app.metrics as m

    class _FakeClient:
        def __init__(self): self.calls = []
        def put_metric_data(self, **kw): self.calls.append(kw)

    fake = _FakeClient()
    monkeypatch.setattr(m, "_get_client", lambda: fake)
    monkeypatch.setattr(m, "NAMESPACE", "DataPond")
    m._put("BytesScanned", 1024, "Bytes", {"Engine": "Athena"})
    assert len(fake.calls) == 1
    kw = fake.calls[0]
    assert kw["Namespace"] == "DataPond"
    datum = kw["MetricData"][0]
    assert datum["MetricName"] == "BytesScanned"
    assert datum["Value"] == 1024.0
    assert datum["Unit"] == "Bytes"
    assert datum["Dimensions"] == [{"Name": "Engine", "Value": "Athena"}]


def test_put_never_raises(monkeypatch):
    import app.metrics as m

    class _Boom:
        def put_metric_data(self, **kw): raise RuntimeError("cloudwatch down")

    monkeypatch.setattr(m, "_get_client", lambda: _Boom())
    # must swallow — metrics are best-effort and cannot break the caller
    m._put("RagQuery", 1, "Count", None)
