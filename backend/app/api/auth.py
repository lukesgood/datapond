"""
DataPond Authentication API

Endpoints:
- POST /api/auth/login    — username/password → JWT token
- POST /api/auth/logout   — invalidate session (client-side)
- GET  /api/auth/me       — current user info
- POST /api/auth/setup    — first-time admin password setup
"""

import os
import json
import uuid
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt as _bcrypt
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

# ── Config ─────────────────────────────────────────────────────────────────────

# Accept either env name — the Helm chart injects JWT_SECRET (from datapond-secrets);
# JWT_SECRET_KEY kept for backwards compatibility. Without this alignment the backend
# silently fell back to the hardcoded default below, so every install shared one
# publicly-known signing key (security hole) and any per-replica/per-upgrade wiring
# difference invalidated active sessions.
SECRET_KEY = (
    os.getenv("JWT_SECRET_KEY")
    or os.getenv("JWT_SECRET")
    or "datapond-dev-secret-change-in-production"
)
ALGORITHM  = "HS256"
TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# Default admin credentials (override via env in production)
DEFAULT_ADMIN_USER     = os.getenv("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "datapond123")

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
            password=os.getenv("POSTGRES_PASSWORD", "dev_password"),
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
            # Ensure password is set if missing
            pw_row = await conn.fetchrow(
                "SELECT password_hash FROM users WHERE username=$1", DEFAULT_ADMIN_USER
            )
            if not pw_row or not pw_row["password_hash"]:
                hashed = _hash_password(DEFAULT_ADMIN_PASSWORD)
                await conn.execute(
                    "UPDATE users SET password_hash=$1, role='admin', is_active=true WHERE username=$2",
                    hashed, DEFAULT_ADMIN_USER
                )

# ── Dependency: get current user from token ────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[dict]:
    """Extract current user from Bearer token. Returns None if not authenticated."""
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return {
            "id": payload.get("sub"),
            "username": payload.get("username"),
            "role": payload.get("role", "viewer"),
        }
    except JWTError:
        return None


async def require_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> dict:
    """Require valid authentication. Raises 401 if missing/invalid."""
    user = await get_current_user(credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def internal_api_key() -> str:
    """Shared secret for trusted in-cluster automation (e.g. scheduled Airflow DAGs)."""
    return (os.getenv("INTERNAL_API_KEY") or "").strip()


def _internal_request(request: Request) -> bool:
    key = internal_api_key()
    return bool(key) and request.headers.get("X-Internal-Key", "") == key


async def require_user_or_internal(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Allow either a logged-in user (Bearer JWT) or trusted in-cluster automation
    presenting the shared X-Internal-Key. The internal identity is an admin-scoped
    service principal so it can ingest into any collection a schedule targets.
    Used by endpoints that scheduled DAGs call back into (e.g. /ingest-source)."""
    if _internal_request(request):
        return {"id": None, "username": "system", "role": "admin", "internal": True}
    return await require_user(credentials)


async def require_admin(user: dict = Depends(require_user)) -> dict:
    """Require admin role."""
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
    hashed = _hash_password(request.password)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # New users must change password on first login
        await conn.execute("""
            INSERT INTO users (id, email, username, password_hash, display_name, role, is_active, require_password_change)
            VALUES (gen_random_uuid(), $1, $2, $3, $4, 'viewer', true, true)
            ON CONFLICT (username) DO UPDATE
              SET password_hash = EXCLUDED.password_hash,
                  display_name  = COALESCE(EXCLUDED.display_name, users.display_name),
                  require_password_change = false
        """,
            f"{request.username}@datapond.local",
            request.username,
            hashed,
            request.display_name or request.username,
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
