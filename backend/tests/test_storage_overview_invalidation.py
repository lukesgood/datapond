"""A write must not leave the console showing the old overview for 30 s."""
import asyncio

from app.api import storage as st


class _S3:
    def create_bucket(self, **kw):
        pass

    def delete_bucket(self, **kw):
        pass


def test_create_and_delete_forget_the_cached_overview(monkeypatch):
    monkeypatch.setattr(st, "get_s3_client", lambda: _S3())
    for call in (lambda: st.create_bucket("b1"), lambda: st.delete_bucket("b1")):
        st._overview_cache["data"], st._overview_cache["ts"] = {"stale": True}, 1e12
        asyncio.run(call())
        assert st._overview_cache["data"] is None
