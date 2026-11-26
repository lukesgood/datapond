"""A REST source follows pagination (it read the first response only, so a paged API
loaded one page), refuses to follow a next link to another host with its credential,
fails rather than load a subset at max_pages, and can send an API key as a query
parameter."""
import asyncio

import httpx
import pytest

from app.connectors import rest
from app.connectors.base import ConnectorType
from app.connectors.rest import RestConfig, RestConnector

ROWS = [{"id": i} for i in range(1, 8)]


def _connector(monkeypatch, handler, **cfg):
    real = httpx.Client
    monkeypatch.setattr(rest.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return RestConnector(RestConfig(name="r", connector_type=ConnectorType.REST_API,
                                    base_url="https://api.x/v1/items", data_path="data", **cfg))


def _read(c):
    return asyncio.run(c.read_data("root"))


def test_page_numbers_until_a_short_page(monkeypatch):
    seen = []

    def h(req):
        page, size = int(req.url.params["page"]), int(req.url.params["per_page"])
        seen.append(page)
        return httpx.Response(200, json={"data": ROWS[(page - 1) * size: page * size]})
    c = _connector(monkeypatch, h, pagination="page", page_size_param="per_page", page_size=3)
    assert _read(c) == ROWS and seen == [1, 2, 3]


def test_offsets_until_a_short_page(monkeypatch):
    def h(req):
        o, l = int(req.url.params["offset"]), int(req.url.params["limit"])
        return httpx.Response(200, json={"data": ROWS[o:o + l]})
    assert _read(_connector(monkeypatch, h, pagination="offset", page_size=4)) == ROWS


def test_a_cursor_from_the_response(monkeypatch):
    def h(req):
        start = int(req.url.params.get("cursor", 0))
        nxt = start + 5 if start + 5 < len(ROWS) else None
        return httpx.Response(200, json={"data": ROWS[start:start + 5], "meta": {"next": nxt}})
    c = _connector(monkeypatch, h, pagination="cursor", cursor_path="meta.next")
    assert _read(c) == ROWS


def test_the_link_header_on_the_same_host(monkeypatch):
    def h(req):
        if "p2" in str(req.url):
            return httpx.Response(200, json={"data": ROWS[4:]})
        return httpx.Response(200, json={"data": ROWS[:4]}, headers={"Link": '</v1/items?p2=1>; rel="next"'})
    assert _read(_connector(monkeypatch, h, pagination="next_link")) == ROWS


def test_a_next_link_to_another_host_is_not_followed(monkeypatch):
    def h(req):
        return httpx.Response(200, json={"data": ROWS, "next": "https://evil.example/steal"})
    c = _connector(monkeypatch, h, pagination="next_link", next_path="next", auth_type="bearer", auth_value="t")
    with pytest.raises(RuntimeError, match="another host"):
        _read(c)


def test_max_pages_fails_instead_of_loading_some(monkeypatch):
    def h(req):
        return httpx.Response(200, json={"data": [{"id": 1}], "next_cursor": "again"})
    c = _connector(monkeypatch, h, pagination="cursor", max_pages=3)
    with pytest.raises(RuntimeError, match="Stopped after 3 pages"):
        _read(c)


def test_an_api_key_in_the_query_string(monkeypatch):
    def h(req):
        assert req.url.params["apikey"] == "k" and "Authorization" not in req.headers
        return httpx.Response(200, json={"data": ROWS[:1]})
    c = _connector(monkeypatch, h, auth_type="api_key_query", auth_param="apikey", auth_value="k")
    assert _read(c) == ROWS[:1]


def test_no_pagination_reads_one_response(monkeypatch):
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(200, json={"data": ROWS})
    assert _read(_connector(monkeypatch, h)) == ROWS and len(calls) == 1
