# DataPond Enterprise — Commercial License (see ee/LICENSE). Not covered by the root Apache-2.0 grant.
"""OIDC SSO endpoints: /api/auth/oidc/login (302 to IdP) + /api/auth/oidc/callback."""
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse

from ee.sso.oidc import (
    OIDCError, build_authorize_url, exchange_code, oidc_enabled,
    state_pop, verify_id_token, _cfg,
)

logger = logging.getLogger(__name__)

router = APIRouter()

COOKIE_MAX_AGE = 24 * 3600
STATE_COOKIE = "oidc_state"
STATE_COOKIE_PATH = "/api/auth/oidc"
STATE_COOKIE_MAX_AGE = 600


def _cookie_secure() -> bool:
    # HTTPS-fronted deployments (the sovereign/on-prem default) → Secure cookies.
    return os.getenv("EXTERNAL_SCHEME", "https").strip().lower() == "https"


async def _pool():
    from app.api.auth import _get_pool
    return await _get_pool()


def _map_role(claims: dict, *, group_claim: str, admin_group: str, default_role: str) -> str:
    groups = claims.get(group_claim)
    if admin_group and isinstance(groups, list) and admin_group in groups:
        return "admin"
    return default_role


async def _upsert_oidc_user(u: dict) -> Optional[dict]:
    """JIT-provision an OIDC user (LDAP-parity semantics).

    Conflict update is scoped WHERE auth_method='oidc' and never touches is_active,
    so (a) a local/ldap account with the same username is never modified — detected
    afterwards and treated as a conflict; (b) a deactivated OIDC user stays deactivated."""
    pool = await _pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (id, email, username, display_name, role, auth_method,
                               external_id, is_active, require_password_change)
            VALUES (gen_random_uuid(), $1, $2, $3, $4, 'oidc', $5, true, false)
            ON CONFLICT (username) DO UPDATE
              SET display_name = EXCLUDED.display_name,
                  email        = EXCLUDED.email,
                  role         = EXCLUDED.role,
                  external_id  = EXCLUDED.external_id
              WHERE users.auth_method = 'oidc'
            """,
            u["email"], u["username"], u["display_name"], u["role"], u["external_id"],
        )
        row = await conn.fetchrow(
            """SELECT id, username, role, auth_method, is_active
               FROM users WHERE username=$1""",
            u["username"],
        )
    if row is None or row["auth_method"] != "oidc":
        return None
    return dict(row)


def _fail(reason: str, detail: str = "") -> RedirectResponse:
    logger.warning("[oidc] sso login failed: reason=%s %s", reason, detail)
    return RedirectResponse(f"/login?error=sso_failed&reason={reason}", status_code=302)


@router.get("/auth/oidc/login")
async def oidc_login():
    if not oidc_enabled():
        raise HTTPException(status_code=404, detail="SSO not enabled")
    try:
        url, state = await build_authorize_url()
    except (OIDCError, Exception) as e:
        return _fail("provider", str(e))
    resp = RedirectResponse(url, status_code=302)
    # Bind the state to THIS browser (login-CSRF / session-fixation guard):
    # the callback requires this cookie to equal the state query param.
    resp.set_cookie(STATE_COOKIE, state, max_age=STATE_COOKIE_MAX_AGE, httponly=True,
                    secure=_cookie_secure(), samesite="lax", path=STATE_COOKIE_PATH)
    return resp


@router.get("/auth/oidc/callback")
async def oidc_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if not oidc_enabled():
        raise HTTPException(status_code=404, detail="SSO not enabled")
    if error or not code or not state:
        return _fail("provider", f"idp error={error!r}")

    # The browser completing the callback must be the one that initiated login
    # (state cookie set by /auth/oidc/login). Plain != is fine: state is
    # single-use + high-entropy random, so timing is not exploitable.
    cookie_state = request.cookies.get(STATE_COOKIE, "")
    if not cookie_state or cookie_state != state:
        return _fail("state", "browser state cookie missing/mismatch")

    try:
        st = await state_pop(state)
    except Exception as e:
        return _fail("state", f"state store error: {e}")
    if not st:
        return _fail("state")

    try:
        tokens = await exchange_code(code, st["verifier"])
        id_token = tokens.get("id_token") if isinstance(tokens, dict) else None
    except (OIDCError, Exception) as e:
        return _fail("exchange", str(e))
    if not id_token:
        return _fail("exchange", "no id_token in response")

    try:
        claims = await verify_id_token(id_token, st["nonce"])
    except (OIDCError, Exception) as e:
        return _fail("token", str(e))

    username = (claims.get("preferred_username") or claims.get("email") or "").strip()
    if not username:
        return _fail("claims", "no preferred_username/email claim")
    try:
        cfg = _cfg()
    except Exception as e:
        return _fail("provider", str(e))
    role = _map_role(claims, group_claim=cfg["group_claim"],
                     admin_group=cfg["admin_group"], default_role=cfg["default_role"])

    row = await _upsert_oidc_user({
        "email": claims.get("email") or f"{username}@sso.local",
        "username": username,
        "display_name": claims.get("name") or username,
        "role": role,
        "external_id": claims.get("sub"),
    })
    if row is None or not row["is_active"]:
        return _fail("account_conflict", f"username={username}")

    from app.api.auth import _create_token
    token = _create_token(str(row["id"]), row["username"], row["role"])
    resp = RedirectResponse("/login?sso=1", status_code=302)
    resp.set_cookie("datapond_token", token, max_age=COOKIE_MAX_AGE,
                    secure=_cookie_secure(), samesite="lax", path="/")
    resp.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
    return resp
