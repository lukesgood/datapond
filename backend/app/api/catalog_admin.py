"""Data catalogs: the admin side of the registry (app/catalog_registry.py).

P1 made each catalog a `data_catalogs` row; adding one meant writing SQL. These routes
are that SQL with its rules held in one place:

- a catalog's name and engine catalog are what SQL calls it, so neither may collide,
  case-insensitively, with another entry's — `resolve()` would pick one silently;
- exactly one entry is the default (two-part names mean it): making one the default
  clears the other in the same transaction, and the default cannot be disabled or
  removed — choose another default first;
- a catalog that a row-level or masking policy names cannot be removed, or have its
  engine name changed, out from under the policy;
- config is a whitelist per kind (validate_config) and never carries a credential; the
  credential is the write-only `secret`, stored encrypted in system_settings.

Listing needs `catalog:read`. Changes need a signed-in administrator — `require_admin`
refuses API keys and IdP access tokens, because a stored credential must not be able
to point the deployment at another catalog.

Every change writes an auth audit row (never the secret) and refreshes the registry,
so this replica sees it at once and the others within the registry refresh interval.

`/catalogs/{name}/grants` (P3) says who may use a catalog — see app/catalog_access.py.
Reading and replacing grants needs a signed-in administrator too.
"""
import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import catalog_access, catalog_registry
from app.api.auth import require_admin, require_permission, require_user

logger = logging.getLogger(__name__)
router = APIRouter()

TEST_TIMEOUT_SECONDS = 10
_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_SECRET_MAX = 4096
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


async def _pool():
    from app.api.connectors import get_db_pool
    return await get_db_pool()


# ── models ───────────────────────────────────────────────────────────────────

class CatalogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: str
    engine_catalog: Optional[str] = None
    config: dict = Field(default_factory=dict)
    secret: Optional[str] = None
    is_default: bool = False
    enabled: bool = True


class CatalogPatch(BaseModel):
    """Every field optional; `secret: null` clears the credential, an absent `secret`
    leaves it. The kind cannot change — a config is only meaningful for its kind."""
    model_config = ConfigDict(extra="forbid")
    engine_catalog: Optional[str] = None
    config: Optional[dict] = None
    secret: Optional[str] = None
    is_default: Optional[bool] = None
    enabled: Optional[bool] = None


# ── helpers ──────────────────────────────────────────────────────────────────

def _public(row) -> dict:
    cfg = row["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg or "{}")
    return {"name": row["name"], "kind": row["kind"], "engine_catalog": row["engine_catalog"],
            "config": dict(cfg or {}), "is_default": bool(row["is_default"]),
            "enabled": bool(row["enabled"]), "has_secret": bool(row["secret_ref"])}


def _entry_public(e) -> dict:
    from app.api.catalog_backend import uses_rest
    return {"name": e.name, "kind": e.kind, "engine_catalog": e.engine_catalog,
            "config": dict(e.config or {}), "is_default": e.is_default,
            "enabled": e.enabled, "has_secret": bool(e.secret_ref),
            "reader": "iceberg_rest" if uses_rest(e) else e.kind}


def _bad(detail: str, status: int = 400):
    raise HTTPException(status_code=status, detail=detail)


def _check_ident(field: str, value: str) -> str:
    if not isinstance(value, str) or not _NAME.match(value):
        _bad(f"{field} must be a bare identifier (letters, digits, _), at most 64 characters.")
    return value


def _check_config(kind: str, config: dict, *, default: bool) -> dict:
    try:
        config = catalog_registry.validate_config(kind, config)
    except ValueError as e:
        _bad(str(e))
    if kind == "glue" and default and config.get("via_rest"):
        _bad("The default Glue catalog is read through the Glue API (writes share it); "
             "via_rest is for additional Glue catalogs.")
    return config


def _check_secret(kind: str, secret: str) -> str:
    if kind != "iceberg_rest":
        _bad(f"A {kind} catalog takes no secret: Glue uses the node's AWS credentials and "
             "Polaris the deployment's Polaris client.")
    if not secret or len(secret) > _SECRET_MAX or _CONTROL.search(secret):
        _bad(f"secret must be 1–{_SECRET_MAX} printable characters.")
    return secret


def _check_clash(rows, name: str, engine: str, *, own: Optional[str] = None) -> None:
    """Neither the name nor the engine catalog may equal another entry's name or engine
    catalog, case-insensitively: resolve() accepts either, so a clash is two entries
    one SQL name could mean."""
    wanted = {name.lower(), engine.lower()}
    for r in rows:
        if r["name"] == own:
            continue
        if wanted & {r["name"].lower(), r["engine_catalog"].lower()}:
            _bad(f"'{r['name']}' (engine catalog '{r['engine_catalog']}') already uses "
                 "that name; SQL could not tell the two apart.", 409)


_POLICY_REFS = """SELECT
    (SELECT count(*) FROM rls_policies WHERE lower(catalog_name) = ANY($1::text[])) AS rls,
    (SELECT count(*) FROM column_masking_policies
      WHERE lower(catalog_name) = ANY($1::text[])) AS masks"""


async def _check_policy_refs(conn, rows, row, action: str) -> None:
    """409 when a policy names this catalog. Policies store the engine's name for it;
    the registry name is counted too. A name another entry also answers to is left out
    — that policy is the other entry's."""
    others = set()
    for r in rows:
        if r["name"] != row["name"]:
            others |= {r["name"].lower(), r["engine_catalog"].lower()}
    names = sorted({row["name"].lower(), row["engine_catalog"].lower()} - others)
    if not names:
        return
    got = await conn.fetchrow(_POLICY_REFS, names)
    rls, masks = int(got["rls"] or 0), int(got["masks"] or 0)
    if rls or masks:
        _bad(f"Cannot {action} catalog '{row['name']}': {rls} row-level and {masks} masking "
             f"polic{'y' if rls + masks == 1 else 'ies'} name it. Delete or re-target "
             "them first.", 409)


_ROWS = """SELECT name, kind, engine_catalog, config, secret_ref, is_default, enabled
             FROM data_catalogs ORDER BY is_default DESC, name FOR UPDATE"""
_CLEAR_DEFAULT = "UPDATE data_catalogs SET is_default = false WHERE is_default AND name <> $1"
_INSERT = """INSERT INTO data_catalogs
               (name, kind, engine_catalog, config, secret_ref, is_default, enabled)
             VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)"""
_UPDATE = """UPDATE data_catalogs
                SET engine_catalog = $2, config = $3::jsonb, secret_ref = $4,
                    is_default = $5, enabled = $6
              WHERE name = $1"""
_DELETE = "DELETE FROM data_catalogs WHERE name = $1"
_PUT_SECRET = """INSERT INTO system_settings (key, value, updated_at)
                 VALUES ($1, $2, NOW())
                 ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"""
_DROP_SECRET = "DELETE FROM system_settings WHERE key = $1"


async def _put_secret(conn, name: str, secret: str) -> str:
    from app.connectors.vault import CredentialVault
    ref = catalog_registry.secret_ref_for(name)
    await conn.execute(_PUT_SECRET, ref, CredentialVault().encrypt_credentials({"v": secret}))
    return ref


async def _audit(pool, admin: dict, event: str, name: str, details: dict) -> None:
    """One auth_audit_log row per change, after the change committed. Best-effort, like
    every audit writer here: a failed audit insert must not undo an admin's change.
    `details` never carries the secret — only whether it was set or cleared."""
    import uuid
    try:
        async with pool.acquire() as c:
            await c.execute(
                """INSERT INTO auth_audit_log
                     (event_type, user_id, user_email, resource, action, result, details)
                   VALUES ($1,$2,$3,$4,'manage_catalog','success',$5)""",
                event, uuid.UUID(admin["id"]) if admin.get("id") else None,
                admin.get("username"), name, json.dumps(details))
    except Exception as e:
        logger.warning("[catalogs] audit of %s %s skipped: %s", event, name, e)


async def _refresh(pool, name: str) -> None:
    """Make the change visible now: reread the registry, drop catalogs built from the
    old config and the table index built from the old catalogs."""
    from app.api import catalog_backend, table_resolver
    from app.connectors import iceberg_catalog
    catalog_backend.reset_rest_cache(name)
    iceberg_catalog.forget_entry(name)
    await catalog_registry.load(pool, force=True)
    table_resolver.reset_catalog_index_cache()
    catalog_access.invalidate()          # a deleted catalog's grants went with it


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("/catalogs", dependencies=[Depends(require_permission("catalog:read"))])
async def list_catalogs(user: dict = Depends(require_user)):
    """Every registry entry this caller may use, enabled or not, without its
    credential — a signed-in admin sees all of them (app/catalog_access.py). `source`
    is `env` when the registry has no rows yet and the entry shown is derived from env."""
    pool = await _pool()
    await catalog_registry.load(pool, force=True)
    access = await catalog_access.for_caller(user)
    source = "registry" if catalog_registry.cached_default_name() is not None else "env"
    return {"source": source,
            "catalogs": [_entry_public(e)
                         for e in catalog_registry.entries(include_disabled=True)
                         if access.allows(e)]}


@router.post("/catalogs", status_code=201)
async def create_catalog(body: CatalogCreate, admin: dict = Depends(require_admin)):
    name = _check_ident("name", body.name)
    if body.kind not in catalog_registry.KINDS:
        _bad(f"kind must be one of {', '.join(catalog_registry.KINDS)}.")
    engine = _check_ident("engine_catalog", body.engine_catalog or name)
    config = _check_config(body.kind, body.config, default=body.is_default)
    if body.secret is not None:
        _check_secret(body.kind, body.secret)
    if body.is_default and not body.enabled:
        _bad("The default catalog must be enabled.", 409)

    pool = await _pool()
    # An empty table means "the env default". Seed it first, or the entry added here
    # would become the only row — and so the default — by accident.
    try:
        await catalog_registry.seed_from_env(pool)
    except Exception as e:
        logger.warning("[catalogs] seed before create skipped: %s", e)
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(_ROWS)
            _check_clash(rows, name, engine)
            if body.is_default:
                await conn.execute(_CLEAR_DEFAULT, name)
            ref = await _put_secret(conn, name, body.secret) if body.secret else None
            await conn.execute(_INSERT, name, body.kind, engine, json.dumps(config), ref,
                               body.is_default, body.enabled)
    await _audit(pool, admin, "catalog_created", name,
                 {"kind": body.kind, "engine_catalog": engine, "config": config,
                  "is_default": body.is_default, "enabled": body.enabled,
                  "secret": "set" if body.secret else "none"})
    await _refresh(pool, name)
    return {"name": name, "kind": body.kind, "engine_catalog": engine, "config": config,
            "is_default": body.is_default, "enabled": body.enabled,
            "has_secret": bool(ref)}


@router.patch("/catalogs/{name}")
async def update_catalog(name: str, body: CatalogPatch, admin: dict = Depends(require_admin)):
    sent = body.model_fields_set
    pool = await _pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(_ROWS)
            row = next((r for r in rows if r["name"] == name), None)
            if row is None:
                _bad(f"No catalog named '{name}'.", 404)
            current = _public(row)
            engine = current["engine_catalog"]
            if "engine_catalog" in sent and body.engine_catalog is not None \
                    and body.engine_catalog != engine:
                engine = _check_ident("engine_catalog", body.engine_catalog)
                _check_clash(rows, name, engine, own=name)
                await _check_policy_refs(conn, rows, row, "rename the engine catalog of")
            is_default = current["is_default"]
            if "is_default" in sent and body.is_default is not None:
                if current["is_default"] and not body.is_default:
                    _bad("A catalog stops being the default only when another becomes it.",
                         409)
                is_default = body.is_default
            enabled = current["enabled"]
            if "enabled" in sent and body.enabled is not None:
                enabled = body.enabled
            if is_default and not enabled:
                _bad("The default catalog cannot be disabled; make another catalog the "
                     "default first." if current["is_default"]
                     else "Enable the catalog before making it the default.", 409)
            config = current["config"]
            if "config" in sent and body.config is not None:
                config = _check_config(row["kind"], body.config, default=is_default)
            elif is_default and not current["is_default"]:
                _check_config(row["kind"], config, default=True)
            ref, secret_change = row["secret_ref"], None
            if "secret" in sent:
                if body.secret is None:
                    if ref:
                        await conn.execute(_DROP_SECRET, ref)
                    ref, secret_change = None, "cleared"
                else:
                    _check_secret(row["kind"], body.secret)
                    ref, secret_change = await _put_secret(conn, name, body.secret), "set"
            if is_default and not current["is_default"]:
                await conn.execute(_CLEAR_DEFAULT, name)
            await conn.execute(_UPDATE, name, engine, json.dumps(config), ref,
                               is_default, enabled)
    changed = [f for f, old, new in (("engine_catalog", current["engine_catalog"], engine),
                                     ("config", current["config"], config),
                                     ("is_default", current["is_default"], is_default),
                                     ("enabled", current["enabled"], enabled))
               if old != new]
    details = {"changed": changed}
    if "config" in changed:
        details["config"] = config
    if secret_change:
        details["secret"] = secret_change
    await _audit(pool, admin, "catalog_updated", name, details)
    await _refresh(pool, name)
    return {"name": name, "kind": row["kind"], "engine_catalog": engine, "config": config,
            "is_default": is_default, "enabled": enabled, "has_secret": bool(ref)}


@router.delete("/catalogs/{name}")
async def delete_catalog(name: str, admin: dict = Depends(require_admin)):
    pool = await _pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(_ROWS)
            row = next((r for r in rows if r["name"] == name), None)
            if row is None:
                _bad(f"No catalog named '{name}'.", 404)
            if row["is_default"]:
                _bad("The default catalog cannot be deleted; make another catalog the "
                     "default first.", 409)
            await _check_policy_refs(conn, rows, row, "delete")
            await conn.execute(_DELETE, name)
            if row["secret_ref"]:
                await conn.execute(_DROP_SECRET, row["secret_ref"])
    await _audit(pool, admin, "catalog_deleted", name,
                 {"kind": row["kind"], "engine_catalog": row["engine_catalog"]})
    await _refresh(pool, name)
    return {"deleted": name}


async def probe(entry, timeout: float) -> dict:
    """List `entry`'s namespaces within `timeout` seconds, on a worker thread. Never
    raises: {ok, namespaces, error, latency_ms}, the error sanitised (no credential,
    no URL userinfo). The Test button and the Services health both use this."""
    from app.api import catalog_backend
    secret = catalog_registry.secret_for(entry)
    started = time.monotonic()
    try:
        reader = catalog_backend.reader_for_entry(entry)
        namespaces = list(await asyncio.wait_for(asyncio.to_thread(reader.list_namespaces),
                                                 timeout=timeout))
        ok, error = True, None
    except asyncio.TimeoutError:
        namespaces, ok, error = [], False, f"No answer within {timeout}s."
    except Exception as e:
        namespaces, ok = [], False
        error = catalog_backend.sanitize_error(e, [secret])
    return {"ok": ok, "namespaces": namespaces, "error": error,
            "latency_ms": int((time.monotonic() - started) * 1000)}


@router.post("/catalogs/{name}/test")
async def test_catalog(name: str, admin: dict = Depends(require_admin)):
    """Try to list the catalog's namespaces within TEST_TIMEOUT_SECONDS. A disabled
    entry can be tested — that is how an admin checks it before enabling it. The
    error is sanitised: no credential, no URL userinfo."""
    from app.api import catalog_backend
    pool = await _pool()
    await catalog_registry.load(pool, force=True)
    entry = next((e for e in catalog_registry.entries(include_disabled=True)
                  if e.name == name), None)
    if entry is None:
        _bad(f"No catalog named '{name}'.", 404)
    # A remembered failure would answer for the catalog without trying it again.
    catalog_backend.reset_rest_cache(entry.name)
    res = await probe(entry, TEST_TIMEOUT_SECONDS)
    return {"ok": res["ok"], "namespaces": res["namespaces"][:20],
            "namespace_count": len(res["namespaces"]), "error": res["error"],
            "latency_ms": res["latency_ms"]}


# ── health: one status per enabled catalog, for the Services page ─────────────
#
# The Test button's probe with a shorter deadline, every catalog at once, cached per
# replica for HEALTH_TTL_SECONDS so the page's 30 s poll does not probe every catalog
# on every open tab. A remembered REST failure (catalog_backend) is reported as the
# error it is rather than retried — the Test button is the way to force a retry.

HEALTH_TIMEOUT_SECONDS = 5
HEALTH_TTL_SECONDS = 60
_health: dict = {}          # entry fingerprint -> (monotonic time, result)


def reset_health_cache() -> None:
    _health.clear()


def _health_key(entry) -> str:
    return json.dumps([entry.name, entry.kind, entry.engine_catalog, entry.config or {},
                       entry.secret_ref], sort_keys=True, default=str)


async def _health_of(entry) -> dict:
    key = _health_key(entry)
    hit = _health.get(key)
    if hit and time.monotonic() - hit[0] < HEALTH_TTL_SECONDS:
        return hit[1]
    res = await probe(entry, HEALTH_TIMEOUT_SECONDS)
    out = {"status": "reachable" if res["ok"] else "error", "error": res["error"],
           "latency_ms": res["latency_ms"] if res["ok"] else None,
           "checked_at": datetime.now(timezone.utc).isoformat()}
    _health[key] = (time.monotonic(), out)
    return out


@router.get("/catalogs/health", dependencies=[Depends(require_permission("catalog:read"))])
async def catalogs_health(user: dict = Depends(require_user)):
    """Reachable or error (sanitised), and latency, for each enabled catalog the
    caller may use. One slow or failing catalog never holds up the others."""
    access = await catalog_access.for_caller(user)
    entries = access.entries()
    results = await asyncio.gather(*(_health_of(e) for e in entries))
    return {"catalogs": [{"name": e.name, "kind": e.kind, "is_default": e.is_default, **r}
                         for e, r in zip(entries, results)],
            "ttl_seconds": HEALTH_TTL_SECONDS}


# ── grants: who may use a catalog (multi-catalog P3, app/catalog_access.py) ────
#
# No grants: the catalog is open to every caller that passes today's checks. One grant
# or more: only the granted users (a service account is a user) and roles, plus
# signed-in admins. PUT replaces the whole list — the console edits it as one — and an
# empty list reopens the catalog.

GRANTS_MAX = 500


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["user", "role"]
    principal: str


class GrantsPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grants: List[GrantIn] = Field(default_factory=list)


_CATALOG_EXISTS = "SELECT name FROM data_catalogs WHERE name = $1"
_GRANTS = """SELECT g.principal_kind, g.principal, g.created_at,
                    u.username, u.email, u.auth_method::text AS auth_method
               FROM catalog_grants g
               LEFT JOIN users u
                 ON g.principal_kind = 'user' AND u.id::text = g.principal
              WHERE g.catalog_name = $1
              ORDER BY g.principal_kind, g.principal"""
_USERS_EXIST = "SELECT id::text AS id FROM users WHERE id = ANY($1::uuid[])"
_GRANTS_DELETE = "DELETE FROM catalog_grants WHERE catalog_name = $1"
_GRANT_INSERT = """INSERT INTO catalog_grants
                     (catalog_name, principal_kind, principal, created_by)
                   VALUES ($1, $2, $3, $4)"""


def _grant_public(r) -> dict:
    out = {"kind": r["principal_kind"], "principal": r["principal"]}
    if r["principal_kind"] == "user":
        # A grant can outlive its user row; a missing row shows as no name rather than
        # hiding the grant.
        out["username"] = r["username"]
        out["email"] = r["email"]
        out["service_account"] = (r["auth_method"] == "service") if r["auth_method"] else None
    created = r["created_at"]
    out["created_at"] = created.isoformat() if hasattr(created, "isoformat") else created
    return out


def _missing_table(exc: BaseException) -> bool:
    return (getattr(exc, "sqlstate", None) == "42P01"
            or type(exc).__name__ == "UndefinedTableError")


async def _catalog_or_404(conn, name: str) -> None:
    if not await conn.fetchrow(_CATALOG_EXISTS, name):
        _bad(f"No catalog named '{name}'.", 404)


async def _read_grants(conn, name: str) -> list:
    return [_grant_public(r) for r in await conn.fetch(_GRANTS, name)]


def _check_grants(body: GrantsPut) -> list:
    """(kind, principal) pairs, deduplicated, in the order given — or 400."""
    from app.permissions import ASSIGNABLE_ROLES
    if len(body.grants) > GRANTS_MAX:
        _bad(f"At most {GRANTS_MAX} grants per catalog.")
    seen, out = set(), []
    for g in body.grants:
        principal = (g.principal or "").strip()
        if g.kind == "role":
            if principal not in ASSIGNABLE_ROLES:
                _bad(f"'{principal[:64]}' is not a role; roles are "
                     f"{', '.join(ASSIGNABLE_ROLES)}.")
        else:
            try:
                principal = str(uuid.UUID(principal))
            except ValueError:
                _bad(f"A user grant names the user by id; '{principal[:64]}' is not one.")
        if (g.kind, principal) not in seen:
            seen.add((g.kind, principal))
            out.append((g.kind, principal))
    return out


@router.get("/catalogs/{name}/grants")
async def get_catalog_grants(name: str, admin: dict = Depends(require_admin)):
    """Who may use the catalog. `restricted` is false when nobody was granted — the
    catalog is then open to everyone with catalog access."""
    pool = await _pool()
    async with pool.acquire() as conn:
        await _catalog_or_404(conn, name)
        try:
            grants = await _read_grants(conn, name)
        except Exception as e:
            if not _missing_table(e):
                raise
            grants = []                      # before migration 0021: nobody granted
    return {"catalog": name, "restricted": bool(grants), "grants": grants}


@router.put("/catalogs/{name}/grants")
async def put_catalog_grants(name: str, body: GrantsPut,
                             admin: dict = Depends(require_admin)):
    """Replace the catalog's grants with `grants`. Users must exist and roles be
    assignable; an empty list reopens the catalog to everyone with catalog access."""
    wanted = _check_grants(body)
    pool = await _pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _catalog_or_404(conn, name)
            user_ids = [p for k, p in wanted if k == "user"]
            if user_ids:
                found = {r["id"] for r in await conn.fetch(_USERS_EXIST, user_ids)}
                missing = [u for u in user_ids if u not in found]
                if missing:
                    _bad(f"No user with id {', '.join(missing[:5])}.")
            try:
                before = await _read_grants(conn, name)
            except Exception as e:
                if _missing_table(e):
                    _bad("Catalog grants need database migration 0021; run the "
                         "migration job and retry.", 409)
                raise
            await conn.execute(_GRANTS_DELETE, name)
            created_by = uuid.UUID(admin["id"]) if admin.get("id") else None
            for kind, principal in wanted:
                await conn.execute(_GRANT_INSERT, name, kind, principal, created_by)
            after = await _read_grants(conn, name)
    await _audit_grants(pool, admin, name, before, after)
    # This replica at once; the others within the grants cache TTL.
    catalog_access.invalidate()
    return {"catalog": name, "restricted": bool(after), "grants": after}


async def _audit_grants(pool, admin: dict, name: str, before: list, after: list) -> None:
    def keys(rows):
        return sorted(f"{g['kind']}:{g['principal']}" for g in rows)
    old, new = keys(before), keys(after)
    await _audit(pool, admin, "catalog_grants_changed", name,
                 {"added": sorted(set(new) - set(old)),
                  "removed": sorted(set(old) - set(new)),
                  "restricted": bool(new)})
