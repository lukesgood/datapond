"""REST and S3 sources cannot reach the platform's own addresses (app/connectors/egress.py)."""
import socket

import httpx
import pytest

from app.connectors import egress


def _resolver(*ips):
    def resolve(host, port, proto=0):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, proto, "", (ip, port))
                for ip in ips]
    return resolve


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "10.43.0.10", "10.42.1.5", "::1",
                                "fd00:ec2::254", "0.0.0.0", "::ffff:127.0.0.1"])
def test_platform_addresses_are_refused(ip):
    with pytest.raises(egress.EgressRefused, match="inside the platform"):
        egress.check_url("https://api.example.com/x", resolve=_resolver(ip))


@pytest.mark.parametrize("ip", ["93.184.216.34", "10.0.3.7", "172.31.5.5", "192.168.1.9"])
def test_public_and_customer_private_addresses_are_allowed(ip):
    egress.check_url("https://api.example.com/x", resolve=_resolver(ip))


def test_one_blocked_address_among_several_refuses():
    with pytest.raises(egress.EgressRefused):
        egress.check_url("https://api.example.com", resolve=_resolver("93.184.216.34", "127.0.0.1"))


def test_only_http_urls_with_a_host():
    for url in ("file:///etc/passwd", "gopher://x", "http://", "ftp://h/x"):
        with pytest.raises(egress.EgressRefused):
            egress.check_url(url, resolve=_resolver("93.184.216.34"))


def test_the_cluster_ranges_can_be_replaced(monkeypatch):
    monkeypatch.setenv("SOURCE_BLOCKED_CIDRS", "10.100.0.0/16")
    egress.check_url("https://svc", resolve=_resolver("10.43.0.10"))
    with pytest.raises(egress.EgressRefused):
        egress.check_url("https://svc", resolve=_resolver("10.100.2.2"))
    with pytest.raises(egress.EgressRefused):          # loopback stays blocked whatever is set
        egress.check_url("https://svc", resolve=_resolver("127.0.0.1"))


def test_the_sample_feed_and_the_platform_store_are_allowed(monkeypatch):
    from app.api.sample_api import sample_api_base_url
    egress.check_url(sample_api_base_url(), resolve=_resolver("127.0.0.1"))
    egress.check_url(sample_api_base_url() + "?page=2", resolve=_resolver("127.0.0.1"))
    with pytest.raises(egress.EgressRefused):            # other backend routes on loopback are not
        egress.check_url("http://127.0.0.1:8000/api/connectors", resolve=_resolver("127.0.0.1"))
    monkeypatch.setenv("S3_ENDPOINT", "http://minio:9000")
    egress.check_url("http://minio:9000", resolve=_resolver("10.43.5.5"))
    with pytest.raises(egress.EgressRefused):
        egress.check_url("http://minio:9001", resolve=_resolver("10.43.5.5"))


def test_a_response_from_a_rebound_address_is_discarded():
    class Stream:
        def __init__(self, ip):
            self.ip = ip

        def get_extra_info(self, k):
            return (self.ip, 443) if k == "server_addr" else None
    bad = httpx.Response(200, json={}, extensions={"network_stream": Stream("169.254.169.254")})
    with pytest.raises(egress.EgressRefused, match="discarded"):
        egress.check_peer(bad, "https://api.example.com")
    egress.check_peer(httpx.Response(200, extensions={"network_stream": Stream("93.184.216.34")}), "https://a")
    egress.check_peer(httpx.Response(200), "https://a")   # no stream info (mock transport): nothing to judge


def test_a_rest_source_pointed_at_metadata_fails_its_test(monkeypatch):
    import asyncio
    from app.connectors.base import ConnectorType
    from app.connectors.rest import RestConfig, RestConnector
    c = RestConnector(RestConfig(name="r", connector_type=ConnectorType.REST_API,
                                 base_url="http://169.254.169.254/latest/meta-data/"))
    res = asyncio.run(c.test_connection())
    assert res.success is False and "inside the platform" in res.message


def test_an_s3_endpoint_inside_the_cluster_is_refused(monkeypatch):
    from app.connectors.base import ConnectorType
    from app.connectors.storage import S3Connector, StorageConfig
    monkeypatch.delenv("S3_ENDPOINT", raising=False)
    c = S3Connector(StorageConfig(name="s", connector_type=ConnectorType.S3, bucket="b",
                                       endpoint_url="http://127.0.0.1:9000"))
    with pytest.raises(egress.EgressRefused):
        c._get_client()


def test_dot_segments_do_not_turn_the_sample_exception_into_any_loopback_route():
    from app.api.sample_api import sample_api_base_url
    base = sample_api_base_url()
    for url in (base + "/../../connectors", base + "/x", base + "/%2e%2e/%2e%2e/connectors", base + "extra"):
        with pytest.raises(egress.EgressRefused):
            egress.check_url(url, resolve=_resolver("127.0.0.1"))
    egress.check_url(base + "/?page=2", resolve=_resolver("127.0.0.1"))


# --- S3 sources: the address each boto3 connection reaches is checked at connect time --

def _local_s3():
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        hits = 0

        def do_GET(self):
            H.hits += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            body = b'<?xml version="1.0"?><ListBucketResult><Name>b</Name></ListBucketResult>'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, H


def _client(url):
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=url, region_name="us-east-1", aws_access_key_id="x",
                        aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}))


def test_a_guarded_s3_endpoint_that_reaches_loopback_sends_nothing(monkeypatch):
    """The name passed check_url, then resolved to loopback (rebinding): the connection is
    refused before the request is written."""
    srv, H = _local_s3()
    url = f"http://localhost:{srv.server_port}"
    monkeypatch.delenv("S3_ENDPOINT", raising=False)
    egress.guard_s3_endpoint(url)
    try:
        with pytest.raises(Exception) as e:
            _client(url).list_objects_v2(Bucket="b")
        assert "inside the platform" in str(e.value) or isinstance(e.value, egress.EgressRefused)
        assert H.hits == 0
    finally:
        egress._guarded.discard(("localhost", srv.server_port))
        srv.shutdown()


def test_unguarded_hosts_and_the_platform_store_are_untouched(monkeypatch):
    srv, H = _local_s3()
    url = f"http://127.0.0.1:{srv.server_port}"
    monkeypatch.setenv("S3_ENDPOINT", url)
    egress.guard_s3_endpoint(url)                     # the install's own store: not guarded
    try:
        assert ("127.0.0.1", srv.server_port) not in egress._guarded
        _client(url).list_objects_v2(Bucket="b")
        assert H.hits == 1
    finally:
        srv.shutdown()
