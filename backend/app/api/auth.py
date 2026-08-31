"""
DataPond Authentication API

Endpoints:
- POST /api/auth/login    — username/password → JWT token
- POST /api/auth/logout   — invalidate session (client-side)
- GET  /api/auth/me       — current user info
- POST /api/auth/setup    — first-time admin password setup
"""

import os
import re
import hmac
import json
import uuid
import hashlib
import secrets
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status, Request

from app.rate_limit import LoginThrottle, client_address
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt as _bcrypt
from pydantic import BaseModel

from app.runtime import is_production, component_secret
from app.permissions import ASSIGNABLE_ROLES, permissions_for
from app.service_accounts import (
    effective_permissions, hash_key, key_matches, looks_like_api_key,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

# ── Config ─────────────────────────────────────────────────────────────────────

# Accept either env name — the Helm chart injects JWT_SECRET (from datapond-secrets);
# JWT_SECRET_KEY kept for backwards compatibility. In production (ENVIRONMENT=production)
# an unset JWT secret now fails closed at import time instead of silently falling back to
# a hardcoded default — every install previously shared one publicly-known signing key
# (security hole) if the env wiring was missed. Local dev still gets an insecure default
# (with a warning) so it keeps working without extra setup.
_jwt = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET")
if not _jwt:
    if is_production():
        raise RuntimeError("JWT_SECRET is required in production (ENVIRONMENT=production).")
    logger.warning("JWT_SECRET unset — using an insecure local-dev key. NOT for production.")
    _jwt = "datapond-local-dev-jwt-secret"
SECRET_KEY = _jwt
ALGORITHM  = "HS256"
TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# Default admin credentials (override via env in production)
DEFAULT_ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
_admin_pw = os.getenv("ADMIN_PASSWORD")
if not _admin_pw:
    if is_production():
        raise RuntimeError("ADMIN_PASSWORD is required in production (ENVIRONMENT=production).")
    logger.warning("ADMIN_PASSWORD unset — using an insecure dev default. NOT for production.")
    _admin_pw = "datapond123"
DEFAULT_ADMIN_PASSWORD = _admin_pw

# auth.sql seeds the admin row with this LITERAL placeholder (not a real bcrypt hash).
# _ensure_admin_exists replaces it with hash(ADMIN_PASSWORD) on first real deploy — a
# valid hash from a later password change is left untouched (only the placeholder/NULL
# is (re)initialized), so operators' password changes are respected.
PLACEHOLDER_ADMIN_HASH = "$2b$12$placeholder_hash_replace_on_first_deploy"

def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=12)).decode()

def _verify_password(password: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

security = HTTPBearer(auto_error=False)

# ── DB pool (shared with connectors) ──────────────────────────────────────────

_db_pool = None

async def _get_pool():
    global _db_pool
    if _db_pool is None or _db_pool._closed:
        _db_pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=5432,
            database=os.getenv("POSTGRES_DB", "datapond"),
            user=os.getenv("POSTGRES_USER", "datapond"),
            password=component_secret("POSTGRES_PASSWORD", "dev_password", component="postgres"),
            min_size=1, max_size=5,
        )
    return _db_pool

# ── Models ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class SetupRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    # Optional real email so password recovery actually works. When omitted we fall
    # back to the synthetic {username}@datapond.local for backward compatibility.
    email: Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# ── Helpers ────────────────────────────────────────────────────────────────────

def _create_token(user_id: str, username: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": user_id, "username": username, "role": role, "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM
    )

async def _ensure_admin_exists():
    """Create default admin on first run if no users have passwords."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE username=$1", DEFAULT_ADMIN_USER
        )
        if not row:
            hashed = _hash_password(DEFAULT_ADMIN_PASSWORD)
            await conn.execute("""
                INSERT INTO users (id, email, username, password_hash, display_name, role, is_active)
                VALUES ($1, $2, $3, $4, $5, 'admin', true)
                ON CONFLICT (username) DO UPDATE
                  SET password_hash = EXCLUDED.password_hash,
                      role = 'admin', is_active = true
            """,
                uuid.UUID("00000000-0000-0000-0000-000000000001"),
                f"{DEFAULT_ADMIN_USER}@datapond.local",
                DEFAULT_ADMIN_USER,
                hashed,
                "Administrator",
            )
            logger.info(f"[auth] Default admin created: {DEFAULT_ADMIN_USER}")
        else:
            # Initialize the admin password if it's missing OR still the auth.sql
            # placeholder (never a real, user-changed hash — those are left untouched).
            pw_row = await conn.fetchrow(
                "SELECT password_hash FROM users WHERE username=$1", DEFAULT_ADMIN_USER
            )
            current = pw_row["password_hash"] if pw_row else None
            if not current or current == PLACEHOLDER_ADMIN_HASH:
                hashed = _hash_password(DEFAULT_ADMIN_PASSWORD)
                await conn.execute(
                    "UPDATE users SET password_hash=$1, role='admin', is_active=true WHERE username=$2",
                    hashed, DEFAULT_ADMIN_USER
                )
                logger.info("[auth] Default admin password initialized from ADMIN_PASSWORD")

# ── Dependency: get current user from token ────────────────────────────────────

# Re-validate a decoded token against the live users row on every request, so a
# deactivated / deleted / role-changed account loses access before the 24h token
# expiry (JWTs are otherwise unrevocable). Default on; ops can disable if the
# per-request PK lookup ever matters (it's a single indexed Aurora read).
AUTH_DB_RECHECK = os.getenv("AUTH_DB_RECHECK", "true").lower() in ("1", "true", "yes")
RECHECK_TIMEOUT_S = float(os.getenv("AUTH_RECHECK_TIMEOUT_S", "2.0"))


async def _recheck_user(uid: str, claims: dict) -> Optional[dict]:
    """Return the token identity with role refreshed from the DB, None to reject.

    - malformed / non-UUID sub            -> None (bad token)
    - user deleted or is_active = false   -> None (revoked access)
    - DB unreachable (transient)          -> fall back to token claims (fail-OPEN
      on infra error: the JWT is still cryptographically valid + unexpired, so a
      DB blip must not 401 every request)
    """
    try:
        uid_uuid = uuid.UUID(str(uid))
    except (ValueError, TypeError, AttributeError):
        return None
    try:
        pool = await _get_pool()
        # Bounded acquire+command timeout: on a saturated 5-conn pool or a slow
        # Aurora, fail OPEN fast (raise -> caught below) rather than hang the hot
        # request path — the recheck must never block a request indefinitely.
        async with pool.acquire(timeout=RECHECK_TIMEOUT_S) as conn:
            row = await conn.fetchrow(
                "SELECT is_active, role FROM users WHERE id = $1", uid_uuid,
                timeout=RECHECK_TIMEOUT_S,
            )
    except Exception as e:                       # infra error / timeout -> fail open
        logger.warning("[auth] user recheck DB error (%s) — using token claims", e)
        return claims
    if row is None or not row["is_active"]:      # deleted / disabled -> reject
        return None
    # Refresh role from the DB so a privilege change (e.g. admin -> viewer) takes
    # effect on the next request instead of at token expiry.
    claims["role"] = row["role"] or claims["role"]
    return claims


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[dict]:
    """Extract current user from Bearer token. Returns None if not authenticated.

    One header carries either credential: a `dp_sk_` prefix marks a service-account
    API key, anything else is treated as a JWT. Clients do not have to know which
    scheme this deployment wants.
    """
    if not credentials:
        return None
    if looks_like_api_key(credentials.credentials):
        return await _resolve_api_key(credentials.credentials)
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    claims = {
        "id": payload.get("sub"),
        "username": payload.get("username"),
        "role": payload.get("role", "viewer"),
    }
    if not AUTH_DB_RECHECK:
        return claims
    if not claims["id"]:
        return None            # recheck on + no sub -> unrevocable identity, reject
    return await _recheck_user(claims["id"], claims)


async def require_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Require valid authentication. Raises 401 if missing/invalid.

    Reuses the identity AuthMiddleware already resolved AND rechecked into
    request.state.user, so an authenticated request does exactly ONE recheck DB
    lookup (in the middleware), not two. Falls back to a fresh resolve if the
    middleware didn't run for this path (defensive; e.g. tests)."""
    user = getattr(request.state, "user", None)
    if user is None:
        user = await get_current_user(credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def internal_api_key() -> str:
    """Shared secret for trusted in-cluster automation."""
    return (os.getenv("INTERNAL_API_KEY") or "").strip()


# Internal-key authentication is deliberately limited to the two callback shapes
# used by unattended automation. ``fullmatch`` and a single non-slash path segment
# prevent prefix/suffix confusion (for example, ``/sync/stream`` or trailing paths).
_INTERNAL_AUTOMATION_ROUTES = (
    ("POST", re.compile(r"/api/ai/collections/[^/]+/ingest-source")),
    ("POST", re.compile(r"/api/connectors/[^/]+/sync")),
)


def is_internal_automation_path(method: str, path: str) -> bool:
    method = (method or "").upper()
    return any(
        method == allowed_method and pattern.fullmatch(path or "") is not None
        for allowed_method, pattern in _INTERNAL_AUTOMATION_ROUTES
    )


def _internal_request(request: Request) -> bool:
    """Validate only the shared secret; route scoping is enforced separately."""
    expected = internal_api_key()
    headers = getattr(request, "headers", None)
    if not expected or headers is None:
        return False
    presented = headers.get("X-Internal-Key", "")
    return hmac.compare_digest(presented, expected)


def is_internal_automation_request(request: Request) -> bool:
    """Return true only for a valid key on an explicitly allowed callback route.

    Method and URL metadata are mandatory. Missing metadata—including incomplete
    request doubles—fails closed rather than weakening route scope.
    """
    method = getattr(request, "method", None)
    url = getattr(request, "url", None)
    path = getattr(url, "path", None) if url is not None else None
    if not method or not path:
        return False
    return is_internal_automation_path(method, path) and _internal_request(request)


async def require_user_or_internal(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Allow a user or the scoped internal automation principal.

    The shared key is accepted only for the exact callback method/path allowlist and
    is validated again here even after middleware admission.
    """
    if is_internal_automation_request(request):
        return {"id": None, "username": "system", "role": "admin", "internal": True}
    return await require_user(request, credentials)


async def require_admin(user: dict = Depends(require_user)) -> dict:
    """Require admin role, and a person rather than a stored credential.

    `app/service_accounts.py` states the rule this enforces: a credential that lives in
    a config file or an environment variable must not be able to reshape the
    deployment, no matter which role its account holds. It withheld `user:manage` and
    `settings:write` from every key's effective set — and then the routes that do those
    things were guarded by this function, which compared `role` and never looked at the
    key's set at all. A key issued on an admin service account could therefore create
    and delete users and rewrite system settings while scoped to `catalog:read`, and
    creating a user is a complete escalation: make a human admin, then sign in as them.

    The refusal belongs here rather than only on those routes, because this is the one
    place that covers every administrative route, including the ones added after this
    was written. Routes an automation legitimately needs are gated on a permission
    instead, where the key's scopes decide.
    """
    if str(user.get("auth_method") or "").lower() == "service":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("This action needs a signed-in administrator; an API key cannot "
                    "perform it."),
        )
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


def require_permission(permission: str):
    """FastAPI dependency factory: require `permission` for the calling user's role.

    Hiding a menu is not access control — the API is where a role has to hold. Use
    this on write endpoints that were previously guarded by nothing more than
    authentication. `require_admin` stays where it is: it is equivalent to a
    permission only the admin role carries, and rewriting those call sites would be
    churn without a change in behaviour.

    The refusal names the permission, so a user can tell an administrator what to
    grant instead of guessing.

    Every denial is written to `security_audit_log` (app/security_audit.py) before
    the 403 is raised, and there is no argument here — or on `record()` itself — a
    caller can use to suppress that. Allows are written too, but only for
    write-shaped permissions; see app/security_audit.py's docstring for why.
    """
    from app.permissions import has_permission
    import app.security_audit as security_audit

    async def _guard(request: Request = None,
                      user: dict = Depends(require_user)) -> dict:
        # A service-account key carries its own effective set (role narrowed by the
        # key's scopes). When present it is authoritative — including when it is
        # empty, or a key scoped down to nothing would silently regain its role.
        granted = user.get("permissions")
        allowed = (permission in granted) if granted is not None \
            else has_permission(user.get("role"), permission)
        route = getattr(getattr(request, "url", None), "path", "") or ""
        method = getattr(request, "method", "") or ""
        addr = client_address(request)
        if not allowed:
            reason = (f"'{permission}' permission required — your role "
                      f"({user.get('role') or 'viewer'}) does not have it.")
            await security_audit.record(
                actor=user, permission=permission, route=route, method=method,
                outcome="denied", reason=reason, client_address=addr,
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)
        if security_audit.is_privileged(permission):
            await security_audit.record(
                actor=user, permission=permission, route=route, method=method,
                outcome="allowed", reason="privileged permission granted",
                client_address=addr,
            )
        return user

    # Declares what this guard enforces, so the route inventory can verify coverage
    # from the application's own dependency graph rather than from a hand-kept list.
    _guard.__datapond_authorization__ = permission
    return _guard


async def require_human(user: dict = Depends(require_user)) -> dict:
    """Reject a service-account credential.

    For surfaces that only make sense with a person present. The assistant panel is
    the case: its confirmation gate exists so a human stands between a proposal and a
    change, and a service account is the owner of its own proposals — it would approve
    them itself, which is precisely what the design forbids.

    There is also nothing to gain. An agent already calls the typed endpoints; routing
    it through a model to pick an action adds nondeterminism and a second round of
    token spend, and leaves the audit trail unable to name an approver.
    """
    if str(user.get("auth_method") or "").lower() == "service":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("The assistant is available to signed-in people only. "
                    "Use the REST API directly with this key."),
        )
    return user


async def require_admin_or_internal(
    user: dict = Depends(require_user_or_internal),
) -> dict:
    """Require an administrator or the scoped internal automation principal."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user

# ── Audit ────────────────────────────────────────────────────────────────────
#
# The unified audit stream (Governance → Activity) reads login/logout events from
# auth_audit_log. record_auth_event is the single best-effort writer used by every
# authentication path (local/LDAP login, passwordless WebAuthn, OIDC SSO). It MUST
# never raise: an audit-write failure can never be allowed to break a real login.

async def record_auth_event(
    event_type: str,
    *,
    user_id=None,
    user_email: Optional[str] = None,
    result: str = "success",
    failure_reason: Optional[str] = None,
    request: Optional[Request] = None,
    details: Optional[dict] = None,
) -> None:
    """Best-effort insert of an auth event into auth_audit_log. Never raises.

    event_type must be a valid audit_event_type enum value (e.g. 'login_success',
    'login_failure', 'logout'). ip_address/user_agent are pulled from the HTTP
    request when available. Failures are swallowed (debug-logged) so authentication
    is never blocked by the audit layer.
    """
    try:
        ip = None
        user_agent = None
        if request is not None:
            client = getattr(request, "client", None)
            ip = getattr(client, "host", None) if client is not None else None
            try:
                user_agent = request.headers.get("user-agent")
            except Exception:
                user_agent = None
        uid = None
        if user_id:
            uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO auth_audit_log
                     (event_type, user_id, user_email, ip_address, user_agent,
                      action, result, failure_reason, details)
                   VALUES ($1,$2,$3,$4::inet,$5,'authenticate',$6,$7,$8)""",
                event_type, uid, user_email, ip, user_agent,
                result, failure_reason, json.dumps(details or {}),
            )
    except Exception as e:
        logger.debug("auth audit skipped (%s): %s", event_type, e)


_login_throttle: Optional["LoginThrottle"] = None


def login_throttle() -> "LoginThrottle":
    """One throttle per process, built on first use.

    Process-local by design for now. The AWS reference runs one or two backend
    replicas, so a per-replica counter costs at most a factor of two on the
    thresholds — a real weakness, but a bounded one, and far better than the nothing
    that was here. A shared store is the fix when replica counts grow; the decision
    logic already takes its clock and state as arguments so that swap is local.
    """
    global _login_throttle
    if _login_throttle is None:
        import time as _time
        _login_throttle = LoginThrottle(clock=_time.monotonic)
    return _login_throttle


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest, http_request: Request = None):
    """Authenticate and return JWT token."""
    # Before anything else, and in particular before the bcrypt verify below. An
    # unthrottled login is not only a guessing oracle: each attempt costs a
    # deliberately expensive hash, so answering them at all is how a single-node
    # deployment is taken down from anywhere.
    address = client_address(http_request)
    wait = login_throttle().retry_after(request.username, address)
    if wait is not None:
        await record_auth_event(
            "login_failure", user_email=request.username, result="failure",
            failure_reason="rate limited", request=http_request,
            details={"username": request.username, "retry_after": wait},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )

    await _ensure_admin_exists()

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, username, password_hash, role, display_name, email,
                          auth_method, is_active, require_password_change
                   FROM users WHERE username=$1""",
                request.username
            )

        # Local password check (works even when LDAP is on — keeps the local admin usable).
        local_ok = bool(row and row["is_active"] and row["password_hash"]
                        and _verify_password(request.password, row["password_hash"]))

        if not local_ok:
            from .ldap_auth import ldap_enabled, ldap_authenticate
            # Never let an LDAP bind shadow an existing LOCAL account with the same
            # username — a wrong local password must NOT fall through to LDAP and hijack
            # (or re-provision) that account.
            if row and row["auth_method"] == "local" and row["password_hash"]:
                raise HTTPException(status_code=401, detail="Invalid username or password")
            # Fall back to LDAP/AD when enabled. On success, auto-provision the directory
            # user so RBAC/RLS/audit treat them like any other account.
            if ldap_enabled():
                ldap_user = await asyncio.to_thread(ldap_authenticate, request.username, request.password)
                if ldap_user:
                    row = await _upsert_ldap_user(ldap_user)
                else:
                    raise HTTPException(status_code=401, detail="Invalid username or password")
            else:
                raise HTTPException(status_code=401, detail="Invalid username or password")

        if not row or not row["is_active"]:
            raise HTTPException(status_code=401, detail="Invalid username or password")
    except HTTPException as exc:
        # Record every rejected credential attempt (best-effort) so the audit stream
        # has a real login-failure signal. user_email carries the attempted username.
        if exc.status_code == 401:
            await record_auth_event(
                "login_failure",
                user_email=request.username,
                result="failure",
                failure_reason=exc.detail,
                request=http_request,
                details={"username": request.username},
            )
            login_throttle().record_failure(request.username, address)
        raise

    login_throttle().record_success(request.username, address)
    token = _create_token(str(row["id"]), row["username"], row["role"])
    await record_auth_event(
        "login_success",
        user_id=row["id"],
        user_email=row["email"],
        result="success",
        request=http_request,
        details={"username": row["username"]},
    )
    return TokenResponse(
        access_token=token,
        user={
            "id": str(row["id"]),
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "email": row["email"],
            "role": row["role"],
            "require_password_change": bool(row["require_password_change"]),
        }
    )


async def _upsert_ldap_user(u: dict):
    """Create/update an LDAP-authenticated user (no local password) and return the row.
    Role is refreshed from LDAP each login so directory group changes propagate.

    The conflict update is scoped to existing LDAP users (WHERE auth_method='ldap') and
    deliberately does NOT touch is_active — so an admin who deactivated a directory user
    isn't silently re-activated on their next login. (login() already refuses to shadow
    a local account, so this conflict only fires for LDAP rows.)"""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (id, email, username, display_name, role, auth_method,
                               external_id, is_active, require_password_change)
            VALUES (gen_random_uuid(), $1, $2, $3, $4, 'ldap', $5, true, false)
            ON CONFLICT (username) DO UPDATE
              SET display_name = EXCLUDED.display_name,
                  email        = EXCLUDED.email,
                  role         = EXCLUDED.role,
                  external_id  = EXCLUDED.external_id
              WHERE users.auth_method = 'ldap'
            """,
            u["email"], u["username"], u["display_name"], u["role"], u.get("external_id"),
        )
        return await conn.fetchrow(
            """SELECT id, username, password_hash, role, display_name, email,
                      is_active, require_password_change
               FROM users WHERE username=$1""",
            u["username"],
        )


@router.get("/auth/me")
async def get_me(user: dict = Depends(require_user)):
    """Get current user info."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, display_name, email, role FROM users WHERE id=$1",
            uuid.UUID(user["id"])
        )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "email": row["email"],
        "role": row["role"],
    }


@router.post("/auth/setup")
async def setup_password(request: SetupRequest, user: dict = Depends(require_permission("user:manage"))):
    """Admin: set password for a user (or create user)."""
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    hashed = _hash_password(request.password)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # New users must change password on first login. This endpoint is also
        # reused by the admin "reset password" action (existing username -> the
        # ON CONFLICT branch) — that path must ALSO force a password change on
        # next login (matches the Reset Password dialog's promise in
        # frontend/app/settings/page.tsx). Previously this cleared the flag,
        # silently undoing the reset's own guarantee.
        # Use the caller-supplied real email when provided (needed for password
        # recovery); otherwise keep the legacy synthetic address for a NEW user.
        provided_email = (request.email or "").strip()
        insert_email = provided_email or f"{request.username}@datapond.local"
        await conn.execute("""
            INSERT INTO users (id, email, username, password_hash, display_name, role, is_active, require_password_change)
            VALUES (gen_random_uuid(), $1, $2, $3, $4, 'viewer', true, true)
            ON CONFLICT (username) DO UPDATE
              SET password_hash = EXCLUDED.password_hash,
                  display_name  = COALESCE(EXCLUDED.display_name, users.display_name),
                  -- Only overwrite an existing user's email when a real one was
                  -- explicitly provided; never clobber it with the synthetic value.
                  email         = COALESCE(NULLIF($5, ''), users.email),
                  require_password_change = true
        """,
            insert_email,
            request.username,
            hashed,
            request.display_name or request.username,
            provided_email,
        )
    return {"message": f"Password set for '{request.username}'"}


@router.post("/auth/change-password")
async def change_password(body: dict, user: dict = Depends(require_user)):
    """Change own password and clear require_password_change flag."""
    new_password = body.get("new_password", "")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    hashed = _hash_password(new_password)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET password_hash=$1, require_password_change=false WHERE id=$2",
            hashed, uuid.UUID(user["id"])
        )
    return {"message": "Password changed successfully"}


@router.post("/auth/logout")
async def logout(http_request: Request = None):
    """Logout (client deletes token)."""
    # Best-effort audit. Logout stays unauthenticated (client just drops the token),
    # so identity is read opportunistically from the request state populated by the
    # auth middleware — a missing identity simply yields no audit row.
    ident = None
    try:
        state = getattr(http_request, "state", None) if http_request is not None else None
        ident = getattr(state, "user", None) if state is not None else None
    except Exception:
        ident = None
    if ident:
        await record_auth_event(
            "logout",
            user_id=ident.get("id"),
            user_email=ident.get("username"),
            result="success",
            request=http_request,
        )
    return {"message": "Logged out"}


# ── Password reset (email-based "forgot password") ──────────────────────────────
#
# Both endpoints are pre-auth (no JWT) and MUST be listed in main.py's AUTH_EXEMPT
# set: "/api/auth/forgot-password" and "/api/auth/reset-password". Security model:
# anti-enumeration (forgot always returns the same 200), tokens are single-use,
# stored only as a SHA-256 hash, and expire after 30 minutes.

RESET_TOKEN_TTL_MINUTES = 30
_GENERIC_FORGOT_RESPONSE = {"message": "If that email exists, a reset link was sent."}


def _hash_reset_token(raw_token: str) -> str:
    """SHA-256 hex of the raw token — only the hash is ever persisted."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _reset_base_url(request: Request) -> str:
    """Base URL for the reset link: APP_BASE_URL if set, else request scheme+host."""
    configured = (os.getenv("APP_BASE_URL") or "").strip()
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


@router.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Start a password reset. ALWAYS returns 200 with a generic message so an
    attacker cannot learn whether an email is registered (no user enumeration).

    On a match to an ACTIVE user: prior unused tokens are invalidated, a new
    URL-safe token is generated, its SHA-256 hash stored with a 30-min expiry,
    and a reset link is emailed (best-effort via SES)."""
    email = (body.email or "").strip()
    if not email:
        return _GENERIC_FORGOT_RESPONSE

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Case-insensitive match; only active local-capable accounts can reset.
        row = await conn.fetchrow(
            "SELECT id, email FROM users WHERE lower(email) = lower($1) AND is_active = true",
            email,
        )
        if row:
            raw_token = secrets.token_urlsafe(32)
            token_hash = _hash_reset_token(raw_token)
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
            try:
                # Best-effort: invalidate any prior unused tokens for this user so
                # only the newest link is live.
                await conn.execute(
                    "UPDATE password_reset_tokens SET used_at = NOW() "
                    "WHERE user_id = $1 AND used_at IS NULL",
                    row["id"],
                )
                await conn.execute(
                    "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
                    "VALUES ($1, $2, $3)",
                    row["id"], token_hash, expires_at,
                )
            except Exception as e:
                # A DB error here must not reveal anything to the caller — log and
                # still return the generic response.
                logger.warning("[auth] failed to persist reset token: %s", e)
                return _GENERIC_FORGOT_RESPONSE

            reset_url = f"{_reset_base_url(request)}/reset?token={raw_token}"
            try:
                from app.email_util import send_email, password_reset_email
                subject, text, html = password_reset_email(reset_url)
                # send_email never raises and returns False when SES isn't
                # configured — we intentionally ignore the result to avoid leaking
                # delivery state to the caller.
                await asyncio.to_thread(send_email, row["email"], subject, text, html)
            except Exception as e:
                logger.warning("[auth] reset email dispatch failed: %s", e)

    return _GENERIC_FORGOT_RESPONSE


@router.post("/auth/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """Complete a password reset using the emailed token.

    Looks up an unused, unexpired token by its hash; sets the new password, clears
    require_password_change, and marks the token used (single-use)."""
    raw_token = (body.token or "").strip()
    new_password = body.new_password or ""
    if not raw_token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    token_hash = _hash_reset_token(raw_token)
    hashed = _hash_password(new_password)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id FROM password_reset_tokens "
            "WHERE token_hash = $1 AND used_at IS NULL AND expires_at > NOW()",
            token_hash,
        )
        if not row:
            raise HTTPException(status_code=400, detail="Invalid or expired reset link")
        async with conn.transaction():
            await conn.execute(
                "UPDATE users SET password_hash = $1, require_password_change = false WHERE id = $2",
                hashed, row["user_id"],
            )
            await conn.execute(
                "UPDATE password_reset_tokens SET used_at = NOW() WHERE id = $1",
                row["id"],
            )
    return {"message": "Password has been reset. You can now sign in."}


# ── User management endpoints ──────────────────────────────────────────────────

@router.get("/auth/users")
async def list_users(admin: dict = Depends(require_permission("user:manage"))):
    """Admin: list all users."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, username, email, display_name, role, is_active,
                   require_password_change, created_at,
                   COALESCE(attributes, '{}'::jsonb) AS attributes
            FROM users
            ORDER BY created_at ASC
        """)

    def _attrs(v):
        if isinstance(v, dict):
            return v
        try:
            return json.loads(v) if v else {}
        except Exception:
            return {}

    return [
        {
            "id": str(r["id"]),
            "username": r["username"] or "",
            "email": r["email"] or "",
            "display_name": r["display_name"] or r["username"] or "",
            "role": r["role"],
            "is_active": r["is_active"],
            "require_password_change": bool(r["require_password_change"]),
            "attributes": _attrs(r["attributes"]),
            "created_at": r["created_at"].isoformat() + "Z" if r["created_at"] else None,
        }
        for r in rows
    ]


@router.patch("/auth/users/{user_id}")
async def update_user(user_id: str, body: dict, admin: dict = Depends(require_permission("user:manage"))):
    """Admin: update user role, active status, display_name."""
    pool = await _get_pool()
    updates = []
    values = []
    idx = 1

    if "role" in body and body["role"] in ASSIGNABLE_ROLES:
        updates.append(f"role = ${idx}"); values.append(body["role"]); idx += 1
    if "is_active" in body:
        updates.append(f"is_active = ${idx}"); values.append(bool(body["is_active"])); idx += 1
    if "display_name" in body:
        updates.append(f"display_name = ${idx}"); values.append(str(body["display_name"])); idx += 1
    if "email" in body:
        updates.append(f"email = ${idx}"); values.append(str(body["email"])); idx += 1
    if "attributes" in body and isinstance(body["attributes"], dict):
        # RLS attributes (department / region / clearance / ...). Whole-object replace.
        updates.append(f"attributes = ${idx}::jsonb"); values.append(json.dumps(body["attributes"])); idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    values.append(uuid.UUID(user_id))
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ${idx}",
            *values
        )
        # Keep user_roles in sync with the minimal users.role so RLS resolution matches.
        if "role" in body and body["role"] in ASSIGNABLE_ROLES:
            try:
                await conn.execute("DELETE FROM user_roles WHERE user_id = $1", uuid.UUID(user_id))
                await conn.execute(
                    """INSERT INTO user_roles (user_id, role_id)
                       SELECT $1, id FROM roles WHERE name = $2 ON CONFLICT DO NOTHING""",
                    uuid.UUID(user_id), body["role"])
            except Exception:
                pass  # user_roles table may not exist yet (pre-migration)
    return {"message": "User updated"}


@router.delete("/auth/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(require_permission("user:manage"))):
    """Admin: delete a user. Cannot delete yourself."""
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM users WHERE id = $1",
            uuid.UUID(user_id)
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted"}


@router.patch("/auth/me")
async def update_me(body: dict, user: dict = Depends(require_user)):
    """Update own display_name or email."""
    pool = await _get_pool()
    updates = []; values = []; idx = 1
    if "display_name" in body:
        updates.append(f"display_name = ${idx}"); values.append(str(body["display_name"])); idx += 1
    if "email" in body:
        updates.append(f"email = ${idx}"); values.append(str(body["email"])); idx += 1
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    values.append(uuid.UUID(user["id"]))
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ${idx}", *values)
    return {"message": "Profile updated"}


@router.get("/me/permissions")
async def my_permissions(user: dict = Depends(require_user)):
    """What this user may do.

    Separate from /api/capabilities on purpose: that endpoint is unauthenticated and
    must never fail, so it cannot answer a per-user question. The UI intersects the
    two — a menu appears when the deployment has the feature AND this role may use it.

    Served from the server rather than read off the token the browser holds, so the
    menu reflects the same source the API enforces from.
    """
    role = user.get("role") or "viewer"
    # A service-account key carries its own effective set (role narrowed by scopes).
    # Reporting the role's full set would overstate what the caller can actually do.
    granted = user.get("permissions")
    return {
        "role": role,
        "permissions": sorted(granted) if granted is not None else sorted(permissions_for(role)),
        "assignable_roles": list(ASSIGNABLE_ROLES),
    }


# ── Service-account API keys ──────────────────────────────────────────────────
# The identity is a `users` row (auth_method='service'); this only resolves the
# credential. See app/service_accounts.py for why it is not a separate entity.

# Verified on every request, so the lookup is cached briefly. The TTL bounds how long
# a revoked key keeps working — short enough that revocation is effectively immediate,
# long enough that a busy agent is not one DB round-trip per call.
_KEY_CACHE: dict = {}
_KEY_CACHE_TTL = 30.0
# The keys of this dict are digests of attacker-chosen strings: anything presented as
# a bearer token gets an entry. Eviction used to happen only when the *same* digest
# was read again after expiry, which never happens for random ones — so the store grew
# for as long as someone kept sending them. app/rate_limit.py makes this argument for
# its own store; the cap and the sweep below are the same answer.
_KEY_CACHE_MAX = 4096

# "No entry" has to be distinguishable from "an entry that says this key is invalid",
# and None cannot be both. It used to be: _cache_get returned the cached value, the
# caller tested `is not None`, and every negative entry read as a miss — so an invalid
# key hit the database on every single request, which is exactly the traffic an
# attacker controls.
_CACHE_MISS = object()


def _cache_sweep(now: float) -> None:
    """Drop what can no longer be returned, then, if still over the cap, the oldest.

    Called on write rather than on a timer, so it runs under the traffic that causes
    the growth. Insertion order is age order here: an entry is only ever written once
    per TTL, never updated in place.
    """
    for digest in [d for d, (_, at) in _KEY_CACHE.items() if (now - at) > _KEY_CACHE_TTL]:
        _KEY_CACHE.pop(digest, None)
    while len(_KEY_CACHE) > _KEY_CACHE_MAX:
        _KEY_CACHE.pop(next(iter(_KEY_CACHE)), None)


def _cache_get(digest: str):
    """The cached identity, None for a key known to be invalid, or `_CACHE_MISS`."""
    entry = _KEY_CACHE.get(digest)
    if not entry:
        return _CACHE_MISS
    resolved, at = entry
    if (time.monotonic() - at) > _KEY_CACHE_TTL:
        _KEY_CACHE.pop(digest, None)
        return _CACHE_MISS
    return resolved


async def _resolve_api_key(raw_key: str) -> Optional[dict]:
    """Identity behind an API key, or None. Never raises."""
    digest = hash_key(raw_key)
    cached = _cache_get(digest)
    if cached is not _CACHE_MISS:
        # Including a cached None: a key we already know is invalid must not cost a
        # database round-trip on every request that presents it.
        return cached
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT k.id AS key_id, k.key_hash, k.status, k.scopes, k.expires_at,
                          u.id, u.username, u.role, u.is_active
                     FROM api_keys k JOIN users u ON u.id = k.user_id
                    WHERE k.key_hash = $1""",
                digest,
            )
    except Exception as e:
        logger.warning(f"[auth] api key lookup failed: {e}")
        return None

    resolved = None
    if row and row["is_active"] and str(row["status"]) == "active" \
            and key_matches(raw_key, row["key_hash"]):
        expires = row["expires_at"]
        if expires is None or expires > datetime.now(expires.tzinfo):
            resolved = {
                "id": str(row["id"]),
                "username": row["username"],
                "role": row["role"],
                "auth_method": "service",
                "api_key_id": str(row["key_id"]),
                "permissions": sorted(
                    effective_permissions(row["role"], list(row["scopes"] or []))),
            }
    now = time.monotonic()
    _KEY_CACHE[digest] = (resolved, now)
    _cache_sweep(now)
    if resolved:
        # Best-effort usage stamp; never let bookkeeping fail a request.
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1::uuid",
                    resolved["api_key_id"])
        except Exception:
            pass
    return resolved

require_admin.__datapond_authorization__ = "role:admin"

require_admin_or_internal.__datapond_authorization__ = "role:admin-or-internal"

require_user_or_internal.__datapond_authorization__ = "role:user-or-internal"
