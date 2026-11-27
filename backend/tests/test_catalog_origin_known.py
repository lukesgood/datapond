"""The catalog says "No source writes this table" only when it could read which syncs
write tables; when that read fails, the origin is unknown, not absent."""
import asyncio

from app.api import catalog


def test_unreadable_sync_facts_mark_the_origin_unknown(monkeypatch):
    async def down():
        raise RuntimeError("database unavailable")
    import app.api.connectors as C
    monkeypatch.setattr(C, "get_db_pool", down)
    links, synced, known = asyncio.run(catalog._table_facts())
    assert synced == {} and known is False


def test_table_models_default_to_known():
    assert catalog.TableInfo(name="t", namespace="n").origin_known is True
