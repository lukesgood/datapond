"""Passwordless passkey/WebAuthn (community). Library-backed via py_webauthn.
Challenges are single-use in Valkey (mirrors ee/sso state_pop, reimplemented here since
community code cannot import from /ee)."""
import base64
import json
import logging
import os
import secrets
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from app.api.auth import require_user, _get_pool, _create_token, get_current_user

logger = logging.getLogger(__name__)
COSE_ALG_ALLOWLIST = [-7, -257]  # ES256, RS256


def _webauthn_cfg() -> dict:
    rp_id = os.getenv("WEBAUTHN_RP_ID", "").strip()
    origin = os.getenv("WEBAUTHN_ORIGIN", "").strip()
    if not origin and rp_id:
        origin = f"https://{rp_id}"
    return {
        "rp_id": rp_id,
        "rp_name": os.getenv("WEBAUTHN_RP_NAME", "DataPond").strip(),
        "origin": origin,
    }


def webauthn_enabled() -> bool:
    cfg = _webauthn_cfg()
    if not cfg["rp_id"] or not cfg["origin"]:
        return False
    # WebAuthn needs a secure context: HTTPS, or localhost for dev.
    return cfg["origin"].startswith("https://") or cfg["rp_id"] == "localhost"


def _redis_client():
    try:
        import redis
        # Prefer REDIS_URL (correct host+port). Do NOT read VALKEY_PORT directly: when a
        # 'valkey'/'redis' service exists, K8s injects VALKEY_PORT=tcp://<ip>:6379, which
        # breaks int() → the client silently falls back to an in-process dict, and with >1
        # backend replica the register/begin challenge is unreachable at register/complete
        # ("Challenge expired") — passkey enrollment never completes.
        url = os.getenv("REDIS_URL")
        if url:
            r = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
        else:
            r = redis.Redis(
                host=os.getenv("VALKEY_HOST", "valkey.datapond.svc.cluster.local"),
                port=int(os.getenv("VALKEY_PORT", "6379").rsplit(":", 1)[-1] or "6379"),
                socket_connect_timeout=2, socket_timeout=2, decode_responses=True,
            )
        r.ping()
        return r
    except Exception:
        return None


# In-process fallback store for dev/tests when Valkey is absent (single-use still enforced).
_mem_challenges: dict = {}


def _challenge_store(nonce: str, challenge_b64: str, ttl: int = 300) -> None:
    r = _redis_client()
    if r:
        r.setex(f"webauthn:chal:{nonce}", ttl, challenge_b64)
    else:
        _mem_challenges[nonce] = challenge_b64


def _challenge_pop(nonce: str) -> Optional[str]:
    r = _redis_client()
    if r:
        # getdel is atomic (Valkey/redis 7+): read+delete in one op so two concurrent
        # replays cannot both observe the challenge before it is consumed.
        return r.getdel(f"webauthn:chal:{nonce}")
    return _mem_challenges.pop(nonce, None)


def _new_nonce() -> str:
    return secrets.token_urlsafe(24)


router = APIRouter(prefix="/auth/webauthn", tags=["webauthn"])


def _require_enabled():
    if not webauthn_enabled():
        raise HTTPException(status_code=404, detail="WebAuthn is not enabled")


async def _build_registration_options(user_id: str, username: str, existing: list):
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement,
        PublicKeyCredentialDescriptor,
    )
    from webauthn.helpers.cose import COSEAlgorithmIdentifier
    cfg = _webauthn_cfg()
    opts = generate_registration_options(
        rp_id=cfg["rp_id"], rp_name=cfg["rp_name"],
        user_id=uuid.UUID(user_id).bytes, user_name=username,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        # Enforce the COSE algorithm allowlist (spec §6/§7): only offer ES256/RS256, so the
        # authenticator can only mint a credential with an allowed alg. Driven from the module
        # constant so the two never drift.
        supported_pub_key_algs=[COSEAlgorithmIdentifier(a) for a in COSE_ALG_ALLOWLIST],
    )
    nonce = _new_nonce()
    _challenge_store(nonce, base64.b64encode(opts.challenge).decode())
    return json.loads(options_to_json(opts)), nonce


class CompleteReq(BaseModel):
    nonce: str
    credential: dict
    name: Optional[str] = None


@router.post("/register/begin")
async def register_begin(user: dict = Depends(require_user)):
    _require_enabled()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT credential_id FROM webauthn_credentials WHERE user_id=$1", uuid.UUID(user["id"])
        )
    opts, nonce = await _build_registration_options(
        user["id"], user["username"], [r["credential_id"] for r in rows]
    )
    return {"nonce": nonce, "options": opts}


@router.post("/register/complete")
async def register_complete(req: CompleteReq, user: dict = Depends(require_user)):
    _require_enabled()
    from webauthn import verify_registration_response
    chal = _challenge_pop(req.nonce)
    if not chal:
        raise HTTPException(status_code=400, detail="Challenge expired or already used")
    cfg = _webauthn_cfg()
    try:
        v = verify_registration_response(
            credential=req.credential,
            expected_challenge=base64.b64decode(chal),
            expected_origin=cfg["origin"], expected_rp_id=cfg["rp_id"],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Registration verification failed: {e}")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO webauthn_credentials (user_id, credential_id, public_key, sign_count, aaguid, name)
               VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (credential_id) DO NOTHING""",
            uuid.UUID(user["id"]), v.credential_id, v.credential_public_key, v.sign_count,
            (uuid.UUID(v.aaguid) if getattr(v, "aaguid", None) else None), req.name,
        )
    return {"status": "ok"}


def _sign_count_ok(stored: int, new: int) -> bool:
    if stored == 0 and new == 0:
        return True          # authenticator doesn't implement a counter
    return new > stored


@router.post("/authenticate/begin")
async def authenticate_begin():
    _require_enabled()
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement
    cfg = _webauthn_cfg()
    opts = generate_authentication_options(
        rp_id=cfg["rp_id"], user_verification=UserVerificationRequirement.PREFERRED,
    )  # no allow_credentials → discoverable/usernameless
    nonce = _new_nonce()
    _challenge_store(nonce, base64.b64encode(opts.challenge).decode())
    return {"nonce": nonce, "options": json.loads(options_to_json(opts))}


class AuthCompleteReq(BaseModel):
    nonce: str
    credential: dict


@router.post("/authenticate/complete")
async def authenticate_complete(req: AuthCompleteReq):
    _require_enabled()
    from webauthn import verify_authentication_response
    from webauthn.helpers import base64url_to_bytes
    chal = _challenge_pop(req.nonce)
    if not chal:
        raise HTTPException(status_code=400, detail="Challenge expired or already used")
    try:
        raw_id = base64url_to_bytes(req.credential["rawId"] if "rawId" in req.credential else req.credential["id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed credential")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT c.id cid, c.public_key, c.sign_count, u.id uid, u.username, u.role, u.is_active,
                      u.require_password_change
               FROM webauthn_credentials c JOIN users u ON u.id = c.user_id
               WHERE c.credential_id = $1""", raw_id)
    # Uniform "Unknown credential" for both unknown credential and disabled account so
    # there is no active/inactive oracle. Lookup runs first so the two are indistinguishable.
    if not row or not row["is_active"]:
        raise HTTPException(status_code=401, detail="Unknown credential")
    cfg = _webauthn_cfg()
    try:
        v = verify_authentication_response(
            credential=req.credential, expected_challenge=base64.b64decode(chal),
            expected_origin=cfg["origin"], expected_rp_id=cfg["rp_id"],
            credential_public_key=row["public_key"], credential_current_sign_count=row["sign_count"],
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {e}")
    if not _sign_count_ok(row["sign_count"], v.new_sign_count):
        raise HTTPException(status_code=401, detail="Possible cloned authenticator (sign count)")
    async with pool.acquire() as conn:
        await conn.execute("UPDATE webauthn_credentials SET sign_count=$1, last_used_at=NOW() WHERE id=$2",
                           v.new_sign_count, row["cid"])
    token = _create_token(str(row["uid"]), row["username"], row["role"])
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": str(row["uid"]), "username": row["username"], "role": row["role"],
                     "require_password_change": bool(row["require_password_change"])}}


@router.get("/credentials")
async def list_credentials(user: dict = Depends(require_user)):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, created_at, last_used_at FROM webauthn_credentials
               WHERE user_id=$1 ORDER BY created_at DESC""", uuid.UUID(user["id"]))
    return [{"id": str(r["id"]), "name": r["name"], "created_at": r["created_at"].isoformat(),
             "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None} for r in rows]


@router.delete("/credentials/{cred_id}")
async def delete_credential(cred_id: str, user: dict = Depends(require_user)):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM webauthn_credentials WHERE id=$1 AND user_id=$2",
                                 uuid.UUID(cred_id), uuid.UUID(user["id"]))
    if res.endswith("0"):
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"status": "deleted"}
