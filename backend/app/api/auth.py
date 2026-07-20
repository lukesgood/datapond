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
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt as _bcrypt
from pydantic import BaseModel

from app.runtime import is_production, component_secret

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
    """Extract current user from Bearer token. Returns None if not authenticated."""
    if not credentials:
        return None
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
    """Require admin role."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


async def require_admin_or_internal(
    user: dict = Depends(require_user_or_internal),
) -> dict:
    """Require an administrator or the scoped internal automation principal."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user

# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """Authenticate and return JWT token."""
    await _ensure_admin_exists()

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

    token = _create_token(str(row["id"]), row["username"], row["role"])
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
async def setup_password(request: SetupRequest, user: dict = Depends(require_admin)):
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
async def logout():
    """Logout (client deletes token)."""
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
async def list_users(admin: dict = Depends(require_admin)):
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
async def update_user(user_id: str, body: dict, admin: dict = Depends(require_admin)):
    """Admin: update user role, active status, display_name."""
    pool = await _get_pool()
    updates = []
    values = []
    idx = 1

    if "role" in body and body["role"] in ("admin", "viewer"):
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
        if "role" in body and body["role"] in ("admin", "viewer"):
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
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
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
