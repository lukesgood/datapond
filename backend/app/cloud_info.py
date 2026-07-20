"""EC2 instance metadata (IMDSv2) for the System page's AWS resource details.

Returns None when not on AWS / IMDS unreachable, so the UI section stays hidden on
non-AWS deployments. Result is cached for the process lifetime — instance identity
is static for the instance's life.
"""
import threading
import urllib.request

_IMDS = "http://169.254.169.254/latest"
_TIMEOUT = 1.5

_cache = {"data": None, "done": False}
_lock = threading.Lock()

# path under meta-data/ → output key
_FIELDS = {
    "instance-id": "instance_id",
    "instance-type": "instance_type",
    "instance-life-cycle": "lifecycle",
    "ami-id": "ami_id",
    "placement/region": "region",
    "placement/availability-zone": "availability_zone",
    "local-ipv4": "private_ip",
    "public-ipv4": "public_ip",
    "local-hostname": "private_hostname",
}


def _token() -> str:
    req = urllib.request.Request(
        _IMDS + "/api/token", method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
    )
    return urllib.request.urlopen(req, timeout=_TIMEOUT).read().decode()


def _get(path: str, token: str):
    req = urllib.request.Request(_IMDS + "/" + path, headers={"X-aws-ec2-metadata-token": token})
    return urllib.request.urlopen(req, timeout=_TIMEOUT).read().decode()


def _fetch():
    token = _token()  # raises if IMDS is unreachable (non-AWS) → treated as no cloud
    out = {"provider": "aws"}
    for path, key in _FIELDS.items():
        try:
            out[key] = _get("meta-data/" + path, token)
        except Exception:
            out[key] = None  # e.g. public-ipv4 404s when the instance has no public IP
    if not out.get("instance_id"):
        return None
    try:
        sg = _get("meta-data/security-groups", token)
        out["security_groups"] = [s for s in sg.splitlines() if s]
    except Exception:
        out["security_groups"] = []
    # Instance tags via IMDS only work when InstanceMetadataTags=enabled — best-effort.
    try:
        out["name"] = _get("meta-data/tags/instance/Name", token)
    except Exception:
        out["name"] = None
    return out


def cloud_info():
    if _cache["done"]:
        return _cache["data"]
    with _lock:
        if not _cache["done"]:
            try:
                _cache["data"] = _fetch()
            except Exception:
                _cache["data"] = None  # IMDS unreachable → not AWS / no cloud section
            _cache["done"] = True
    return _cache["data"]
