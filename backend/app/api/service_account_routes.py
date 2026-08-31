"""Service accounts and their API keys — admin-managed.

A service account is a `users` row with `auth_method='service'`. It cannot log in:
there is no password, and the login handler requires `password_hash`. Its credential
is an API key, which `auth.get_current_user` resolves.

Only an administrator manages these. A credential that can mint further credentials
is a credential that cannot be contained.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import _get_pool, record_auth_event, require_admin
from app.permissions import ASSIGNABLE_ROLES, permissions_for
from app.service_accounts import NEVER_FOR_SERVICE_ACCOUNTS, effective_permissions, generate_key

logger = logging.getLogger(__name__)
router = APIRouter()


class ServiceAccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    role: str = "ai_engineer"
    description: Optional[str] = None


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scopes: List[str] = Field(default_factory=list)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=3650)


def _account_username(name: str) -> str:
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.strip().lower())
    return f"svc-{slug}"[:64]


@router.get("/service-accounts")
async def list_service_accounts(admin: dict = Depends(require_admin)):
    """Service accounts with their keys. Key material is never returned."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        accounts = await conn.fetch(
            """SELECT id, username, display_name, role, is_active, created_at
                 FROM users WHERE auth_method = 'service' ORDER BY created_at DESC""")
        keys = await conn.fetch(
            """SELECT id, user_id, name, key_prefix, status, scopes,
                      expires_at, last_used_at, created_at
                 FROM api_keys ORDER BY created_at DESC""")

    by_user: dict = {}
    for k in keys:
        by_user.setdefault(str(k["user_id"]), []).append({
            "id": str(k["id"]), "name": k["name"], "key_prefix": k["key_prefix"],
            "status": str(k["status"]), "scopes": list(k["scopes"] or []),
            "expires_at": k["expires_at"], "last_used_at": k["last_used_at"],
            "created_at": k["created_at"],
        })

    return {"accounts": [{
        "id": str(a["id"]), "username": a["username"],
        "display_name": a["display_name"], "role": a["role"],
        "is_active": a["is_active"], "created_at": a["created_at"],
        "permissions": sorted(effective_permissions(a["role"], [])),
        "keys": by_user.get(str(a["id"]), []),
    } for a in accounts],
        "assignable_roles": [r for r in ASSIGNABLE_ROLES if r != "admin"],
        "grantable_permissions": sorted(
            set().union(*(permissions_for(r) for r in ASSIGNABLE_ROLES))
            - set(NEVER_FOR_SERVICE_ACCOUNTS)),
    }


@router.post("/service-accounts", status_code=201)
async def create_service_account(body: ServiceAccountCreate, admin: dict = Depends(require_admin)):
    if body.role not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown role '{body.role}'")
    # The listing above offers every assignable role except this one, and the handler
    # accepted it anyway — the API took exactly what its own response said was not on
    # offer. An admin key is the widest credential in the product, and it is the one
    # shape of credential that gets copied into a config file.
    if body.role == "admin":
        raise HTTPException(
            status_code=400,
            detail="A service account cannot hold the admin role. Grant the "
                   "permissions it needs through its key's scopes instead.")

    username = _account_username(body.name)
    pool = await _get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO users
                       (id, email, username, display_name, role, is_active, auth_method)
                   VALUES (gen_random_uuid(), $1, $2, $3, $4, true, 'service')
                   RETURNING id""",
                f"{username}@service.datapond.local", username,
                body.description or body.name, body.role)
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"'{username}' already exists")
        logger.warning(f"[svc] create failed: {e}")
        raise HTTPException(status_code=500, detail="Could not create the service account")

    await record_auth_event("user_created", user_id=admin.get("id"),
                            result="success", details={"service_account": username})
    return {"id": str(row["id"]), "username": username, "role": body.role}


@router.post("/service-accounts/{account_id}/keys", status_code=201)
async def create_api_key(account_id: str, body: ApiKeyCreate,
                         admin: dict = Depends(require_admin)):
    """Issue a key. The plaintext is in this response and nowhere else, ever."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        acct = await conn.fetchrow(
            "SELECT id, role FROM users WHERE id = $1::uuid AND auth_method = 'service'",
            account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Service account not found")

        granted = effective_permissions(acct["role"], body.scopes)
        if body.scopes and not granted:
            raise HTTPException(
                status_code=400,
                detail=("None of the requested scopes are held by this account's role "
                        f"({acct['role']}), so the key would grant nothing."))

        key, prefix, digest = generate_key()
        expires = None
        if body.expires_in_days:
            expires = await conn.fetchval(
                "SELECT NOW() + ($1 || ' days')::interval", str(body.expires_in_days))
        await conn.execute(
            """INSERT INTO api_keys (user_id, name, key_prefix, key_hash, scopes, expires_at)
               VALUES ($1::uuid, $2, $3, $4, $5, $6)""",
            account_id, body.name, prefix, digest, list(body.scopes or []), expires)

    await record_auth_event("api_key_created", user_id=admin.get("id"), result="success",
                            details={"account": account_id, "key_name": body.name})
    return {
        "key": key,
        "key_prefix": prefix,
        "expires_at": expires,
        "permissions": sorted(granted),
        "warning": "Copy this key now — it is not stored and cannot be shown again.",
    }


@router.delete("/service-accounts/keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: str, admin: dict = Depends(require_admin)):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE api_keys SET status = 'revoked', revoked_at = NOW(),
                                   revoked_by = $2::uuid
                WHERE id = $1::uuid AND status = 'active'""",
            key_id, admin.get("id"))
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Key not found or already revoked")
    await record_auth_event("api_key_revoked", user_id=admin.get("id"),
                            result="success", details={"key_id": key_id})
    return None


@router.delete("/service-accounts/{account_id}", status_code=204)
async def delete_service_account(account_id: str, admin: dict = Depends(require_admin)):
    """Delete the account; its keys go with it (ON DELETE CASCADE)."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM users WHERE id = $1::uuid AND auth_method = 'service'", account_id)
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Service account not found")
    await record_auth_event("user_deleted", user_id=admin.get("id"),
                            result="success", details={"service_account": account_id})
    return None
