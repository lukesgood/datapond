"""Where a REST or S3 source may send requests.

A source's URL is typed by a person holding connector:write, and the backend fetches it
and stores the answer in a lake table. Without a check that is a way to make the
backend read services only it can reach: itself on loopback, the instance metadata
service on link-local, and every pod and Service in the cluster (k3s puts them in
10.42.0.0/16 and 10.43.0.0/16). So those addresses are refused. A customer's own
private network (a VPC API on 10.0.x.x, say) stays allowed: reaching internal systems
is what sources are for.

Two checks, because a name can resolve differently the second time (DNS rebinding):
`check_url` resolves the host before the request and refuses if any address is blocked;
`check_peer` reads the address the connection actually used and refuses the response
if it is blocked, so nothing from it is stored.

An S3 source's endpoint gets the same two checks, done differently because boto3 hides
its responses' connections: `check_url` when the client is made, then `guard_s3_endpoint`
registers the endpoint's host so every new connection boto3 opens to it is checked at
connect time, before a byte is sent (a patch on botocore's connection classes that
leaves every other host — Glue, Bedrock, the platform's own S3 — untouched).

Two platform addresses are allowed: the built-in sample REST source (served by the
backend on 127.0.0.1; its exact URL only) and the install's own object store
(S3_ENDPOINT, e.g. in-cluster MinIO), which an S3 source may read.

SOURCE_BLOCKED_CIDRS (comma-separated) replaces the cluster ranges, e.g. for a cluster
with other pod/Service CIDRs; loopback, link-local and "this network" are always blocked.
"""
import ipaddress
import os
import socket
from typing import Iterable, List, Optional
from urllib.parse import urlparse

ALWAYS_BLOCKED = ("127.0.0.0/8", "::1/128", "0.0.0.0/8", "169.254.0.0/16", "fe80::/10",
                  "fd00:ec2::254/128", "::ffff:127.0.0.0/104", "::ffff:169.254.0.0/112")
CLUSTER_DEFAULT = "10.42.0.0/16,10.43.0.0/16"


class EgressRefused(ValueError):
    pass


def blocked_networks() -> List[ipaddress._BaseNetwork]:
    extra = os.getenv("SOURCE_BLOCKED_CIDRS", CLUSTER_DEFAULT)
    nets = []
    for c in list(ALWAYS_BLOCKED) + [x.strip() for x in extra.split(",") if x.strip()]:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            continue
    return nets


def _blocked(ip: str, nets: Iterable) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return True                        # not an address we can judge: refuse
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr.version == n.version and addr in n for n in nets)


def _sample_prefix() -> Optional[str]:
    try:
        from app.api.sample_api import sample_api_base_url
        return sample_api_base_url().rstrip("/")
    except Exception:
        return None


def is_sample(url: str) -> bool:
    """Exactly the sample feed: same scheme, host and port, and the same path once dot
    segments are resolved (httpx resolves them, so a prefix match would let
    `<feed>/../../connectors` reach any loopback route). Query parameters are fine."""
    prefix = _sample_prefix()
    if not prefix:
        return False
    try:
        import httpx
        a, b = httpx.URL(prefix), httpx.URL(url or "")
    except Exception:
        return False
    return ((a.scheme, a.host, a.port) == (b.scheme, b.host, b.port)
            and b.path.rstrip("/") == a.path.rstrip("/") and "%2e" not in str(b.raw_path).lower())


def is_platform_storage(url: str) -> bool:
    """The install's own object store (S3_ENDPOINT, e.g. in-cluster MinIO on the
    Sovereign profiles): a source may read it, as the Storage page does."""
    own = (os.getenv("S3_ENDPOINT") or "").strip().rstrip("/")
    if not own:
        return False
    a, b = urlparse(own), urlparse(url or "")
    return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)


def check_url(url: str, resolve=socket.getaddrinfo) -> None:
    """Raise EgressRefused unless `url` is http(s) and its host resolves only to
    addresses outside the blocked ranges."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise EgressRefused(f"Only http:// and https:// URLs with a host can be used ({url!r}).")
    if is_sample(url) or is_platform_storage(url):
        return
    try:
        infos = resolve(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                        proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise EgressRefused(f"Could not resolve {parsed.hostname}: {e}")
    nets = blocked_networks()
    bad = sorted({i[4][0] for i in infos if _blocked(i[4][0], nets)})
    if bad:
        raise EgressRefused(
            f"{parsed.hostname} resolves to {', '.join(bad)}, an address inside the platform "
            "(loopback, instance metadata or the cluster network); sources cannot reach it.")


def check_peer(response, url: str) -> None:
    """Refuse a response whose connection went to a blocked address (the name resolved
    differently after check_url)."""
    if is_sample(url):
        return
    stream = (getattr(response, "extensions", None) or {}).get("network_stream")
    peer = stream.get_extra_info("server_addr") if stream is not None else None
    if peer and _blocked(str(peer[0]), blocked_networks()):
        raise EgressRefused(f"The connection went to {peer[0]}, an address inside the platform; "
                            "the response was discarded.")


# ── S3 sources: check the address each boto3 connection actually reaches ────────────
_guarded = set()            # (host, port) of S3 source endpoints
_installed = False


def _host_port(url: str):
    u = urlparse(url or "")
    return (u.hostname or "").lower(), u.port or (443 if u.scheme == "https" else 80)


def guard_s3_endpoint(url: str) -> None:
    """Have every connection boto3 opens to this endpoint checked when it connects. The
    install's own object store is not guarded (it is allowed and may be in-cluster)."""
    if not url or is_platform_storage(url):
        return
    _install_boto_peer_check()
    _guarded.add(_host_port(url))


def _check_socket(host: str, port: int, sock) -> None:
    if ((host or "").lower(), port) not in _guarded:
        return
    try:
        peer = sock.getpeername()[0]
    except OSError:
        return
    if _blocked(str(peer), blocked_networks()):
        try:
            sock.close()
        finally:
            raise EgressRefused(f"{host} connected to {peer}, an address inside the platform; "
                                "nothing was sent.")


def _install_boto_peer_check() -> None:
    global _installed
    if _installed:
        return
    from botocore.awsrequest import AWSHTTPConnection, AWSHTTPSConnection
    for cls in (AWSHTTPConnection, AWSHTTPSConnection):
        original = cls._new_conn

        def _new_conn(self, _original=original):
            sock = _original(self)
            _check_socket(self.host, self.port, sock)
            return sock
        cls._new_conn = _new_conn
    _installed = True
