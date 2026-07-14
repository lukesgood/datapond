def test_build_messages_uses_engine_dialect(monkeypatch):
    import app.api.ai_sql as ai
    monkeypatch.setenv("QUERY_ENGINE", "athena")
    system, _ = ai._build_messages("ctx", "count rows", None)
    assert "Athena" in system and "AwsDataCatalog" in system
    assert "The query engine is Trino." not in system


def test_build_messages_trino_default(monkeypatch):
    import app.api.ai_sql as ai
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    system, _ = ai._build_messages("ctx", "count rows", None)
    assert "Trino" in system and "iceberg.<schema>" in system
