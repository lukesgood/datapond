def test_build_messages_uses_the_trino_dialect(monkeypatch):
    """One engine since 2.4: the prompt names Trino and the `iceberg` prefix even
    where a release still carries QUERY_ENGINE=athena in its env."""
    import app.api.ai_sql as ai
    monkeypatch.setenv("QUERY_ENGINE", "athena")
    system, _ = ai._build_messages("ctx", "count rows", None)
    assert "Trino" in system and "iceberg.<schema>" in system
    assert "Athena" not in system and "AwsDataCatalog" not in system


def test_build_messages_trino_default(monkeypatch):
    import app.api.ai_sql as ai
    monkeypatch.delenv("QUERY_ENGINE", raising=False)
    system, _ = ai._build_messages("ctx", "count rows", None)
    assert "Trino" in system and "iceberg.<schema>" in system
