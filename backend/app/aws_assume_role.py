"""STS AssumeRole for a data catalog in another AWS account (registry `role_arn`).

Temporary credentials are cached per (entry, role, external id) and fetched again
REFRESH_MARGIN_SECONDS before they expire. Nothing here logs or returns a credential;
an STS failure is reduced to its error code."""
import re
import threading
import time
from datetime import datetime, timezone

SESSION_DURATION_SECONDS = 3600
REFRESH_MARGIN_SECONDS = 300

ROLE_ARN = re.compile(r"^arn:aws(-[a-z]+)*:iam::\d{12}:role/[\w+=,.@/-]{1,128}$")
EXTERNAL_ID = re.compile(r"^[\w+=,.@:/-]{2,1224}$")

_lock = threading.Lock()
_cache: dict = {}   # key -> (credentials dict, expiry datetime)
_failures: dict = {}  # key -> (monotonic time, message); a refused role is not retried at once
FAILURE_TTL_SECONDS = 30


class AssumeRoleError(RuntimeError):
    """The role could not be assumed; the message carries no credential."""


def validate_role(role_arn, external_id=None) -> None:
    if not isinstance(role_arn, str) or not ROLE_ARN.match(role_arn):
        raise ValueError("role_arn must look like arn:aws:iam::<12-digit account>:role/<name>.")
    if external_id is not None and (not isinstance(external_id, str)
                                    or not EXTERNAL_ID.match(external_id)):
        raise ValueError("external_id must be 2-1224 characters of letters, digits and _+=,.@:/-")


def _now():
    return datetime.now(timezone.utc)


def forget(name=None) -> None:
    with _lock:
        for store in (_cache, _failures):
            for key in [k for k in store if name is None or k[0] == name]:
                store.pop(key, None)


def assumed_credentials(name, role_arn, external_id=None, region=None) -> dict:
    """{'access_key', 'secret_key', 'token'} for `role_arn`, session name
    datapond-catalog-<name>."""
    validate_role(role_arn, external_id)
    key = (name, role_arn, external_id or "")
    with _lock:
        hit = _cache.get(key)
        if hit and (hit[1] - _now()).total_seconds() > REFRESH_MARGIN_SECONDS:
            return dict(hit[0])
        failed = _failures.get(key)
        if failed and time.monotonic() - failed[0] < FAILURE_TTL_SECONDS:
            raise AssumeRoleError(failed[1])
    try:
        import boto3
        params = {"RoleArn": role_arn, "RoleSessionName": f"datapond-catalog-{name}"[:64],
                  "DurationSeconds": SESSION_DURATION_SECONDS}
        if external_id:
            params["ExternalId"] = external_id
        resp = boto3.client("sts", region_name=region or None).assume_role(**params)
        c = resp["Credentials"]
        creds = {"access_key": c["AccessKeyId"], "secret_key": c["SecretAccessKey"],
                 "token": c["SessionToken"]}
        expiry = c["Expiration"]
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    except Exception as e:
        code = ""
        resp_err = getattr(e, "response", None)
        if isinstance(resp_err, dict):
            code = (resp_err.get("Error") or {}).get("Code") or ""
        msg = (f"could not assume the role for catalog '{name}'"
               + (f" ({code})" if re.fullmatch(r"[A-Za-z]{1,64}", code) else "")
               + ": check the role's trust policy and the node role's sts:AssumeRole "
                 "permission.")
        with _lock:
            _failures[key] = (time.monotonic(), msg)
        raise AssumeRoleError(msg) from None
    with _lock:
        _cache[key] = (creds, expiry)
        _failures.pop(key, None)
    return dict(creds)


def _role_creds(entry):
    cfg = entry.config or {}
    if not cfg.get("role_arn"):
        return None
    return assumed_credentials(entry.name, cfg["role_arn"], cfg.get("external_id"),
                               cfg.get("region"))


def glue_credential_props(entry) -> dict:
    """pyiceberg GlueCatalog properties carrying the assumed credentials ({} without
    a role_arn)."""
    c = _role_creds(entry)
    if not c:
        return {}
    return {"glue.access-key-id": c["access_key"], "glue.secret-access-key": c["secret_key"],
            "glue.session-token": c["token"], "s3.access-key-id": c["access_key"],
            "s3.secret-access-key": c["secret_key"], "s3.session-token": c["token"]}


def rest_credential_props(entry) -> dict:
    """pyiceberg RestCatalog properties (SigV4 signer `client.*` + S3 FileIO)."""
    c = _role_creds(entry)
    if not c:
        return {}
    return {"client.access-key-id": c["access_key"], "client.secret-access-key": c["secret_key"],
            "client.session-token": c["token"], "s3.access-key-id": c["access_key"],
            "s3.secret-access-key": c["secret_key"], "s3.session-token": c["token"]}
