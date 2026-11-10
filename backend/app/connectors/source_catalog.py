"""The registry row of a Trino-backed connection.

Every connection whose engine is Trino (trino_source.engine_of) owns one `data_catalogs`
row of kind `trino_source`: `engine_catalog` is the Trino catalog name `src_<slug>`,
`config` names the connection. Its grants are not edited by hand: the connection's
owner and its connector_members are projected into `catalog_grants` as user grants, so
a source is visible in SQL to exactly the people the Sources page shares it with — and
open to everyone when nobody owns it (a sample, or a pre-ownership row), the same rule
every other catalog follows (app/catalog_access.py).

All functions take the caller's connection and run inside the caller's transaction, so a
connection and its catalog appear and disappear together. The SQL issued, in order of
appearance (tests answer exactly these):

  register:      SELECT name, engine_catalog FROM data_catalogs
                 INSERT INTO data_catalogs (name, kind, engine_catalog, config, is_default, enabled)
  catalog_for:   SELECT engine_catalog FROM data_catalogs WHERE kind = 'trino_source' AND config->>'connection_id' = $1
  unregister:    DELETE FROM data_catalogs WHERE kind = 'trino_source' AND config->>'connection_id' = $1 RETURNING engine_catalog
  sync_grants:   catalog_for; SELECT owner_id FROM connector_connections WHERE id = $1::uuid
                 SELECT user_id FROM connector_members WHERE connection_id = $1::uuid
                 DELETE FROM catalog_grants WHERE catalog_name = $1
                 INSERT INTO catalog_grants (catalog_name, principal_kind, principal) VALUES ($1, 'user', $2)
  ensure_rows:   SELECT c.id, c.name, c.connector_type FROM connector_connections c LEFT JOIN data_catalogs d … WHERE d.name IS NULL
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from .base import ConnectorType
from .trino_source import RESERVED_CATALOGS, engine_of, source_slug, unique_slug

logger = logging.getLogger(__name__)

KIND = "trino_source"
RESERVED = RESERVED_CATALOGS

_TAKEN = "SELECT name, engine_catalog FROM data_catalogs"
_INSERT = """INSERT INTO data_catalogs (name, kind, engine_catalog, config, is_default, enabled)
             VALUES ($1, $2, $3, $4::jsonb, false, true)"""
_FOR = ("SELECT engine_catalog FROM data_catalogs WHERE kind = 'trino_source' "
        "AND config->>'connection_id' = $1")
_DELETE = ("DELETE FROM data_catalogs WHERE kind = 'trino_source' "
           "AND config->>'connection_id' = $1 RETURNING engine_catalog")
_OWNER = "SELECT owner_id FROM connector_connections WHERE id = $1::uuid"
_MEMBERS = "SELECT user_id FROM connector_members WHERE connection_id = $1::uuid"
_CLEAR_GRANTS = "DELETE FROM catalog_grants WHERE catalog_name = $1"
_GRANT = ("INSERT INTO catalog_grants (catalog_name, principal_kind, principal) "
          "VALUES ($1, 'user', $2) ON CONFLICT DO NOTHING")
_UNREGISTERED = """SELECT c.id, c.name, c.connector_type FROM connector_connections c
                   LEFT JOIN data_catalogs d
                     ON d.kind = 'trino_source' AND d.config->>'connection_id' = c.id::text
                  WHERE d.name IS NULL ORDER BY c.created_at"""


def is_trino_type(connector_type) -> bool:
    try:
        return engine_of(ConnectorType(str(connector_type))) == "trino"
    except ValueError:
        return False


async def register(conn, *, connection_id: str, name: str, connector_type: str) -> str:
    """Insert the connection's registry row and return its Trino catalog name. The
    name is unique against every registry name and engine catalog and against the
    catalogs the chart renders itself."""
    import asyncpg
    config = {"connection_id": str(connection_id), "connector_type": str(connector_type)}
    last = None
    for _attempt in range(3):
        taken = set(RESERVED)
        for r in await conn.fetch(_TAKEN):
            taken |= {r["name"], r["engine_catalog"]}
        slug = unique_slug(source_slug(name), taken)
        try:
            # A savepoint: a concurrent create may have taken the slug between the read
            # and the insert; the unique constraint says so and the next read sees it.
            async with conn.transaction():
                await conn.execute(_INSERT, slug, KIND, slug, json.dumps(config))
            return slug
        except asyncpg.UniqueViolationError as e:
            last = e
    raise RuntimeError(f"could not register a catalog for {name!r}: {last}")


async def catalog_for(conn, connection_id: str) -> Optional[str]:
    return await conn.fetchval(_FOR, str(connection_id))


async def unregister(conn, connection_id: str) -> Optional[str]:
    """Remove the row (its grants cascade); the catalog name removed, or None."""
    return await conn.fetchval(_DELETE, str(connection_id))


async def sync_grants(conn, connection_id: str) -> List[str]:
    """Replace the catalog's grants with the connection's owner and members. Returns
    the user ids written; an unowned, unshared connection gets none (open)."""
    catalog = await catalog_for(conn, connection_id)
    if not catalog:
        return []
    principals: List[str] = []
    owner = await conn.fetchval(_OWNER, str(connection_id))
    if owner:
        principals.append(str(owner))
    for r in await conn.fetch(_MEMBERS, str(connection_id)):
        if r["user_id"] and str(r["user_id"]) not in principals:
            principals.append(str(r["user_id"]))
    await conn.execute(_CLEAR_GRANTS, catalog)
    for p in principals:
        await conn.execute(_GRANT, catalog, p)
    return principals


_LEGACY_URL_ROWS = """SELECT id, config_encrypted FROM connector_connections
                      WHERE connector_type = 'database_url' ORDER BY created_at"""


async def rewrite_legacy_rows(conn) -> int:
    """A connection stored before 2.5 as `database_url` becomes the PostgreSQL or MySQL
    row its URL described (the console has no card for the URL type any more, so such
    a row could not be edited). The registry entry's connector_type follows. A row the
    vault cannot open, or whose URL names another database, is left as it is and logged."""
    from .base import ConnectorType
    from .trino_source import normalise_type_and_config
    from .vault import CredentialVault
    vault = CredentialVault()
    rewritten = 0
    for r in await conn.fetch(_LEGACY_URL_ROWS):
        try:
            kind, config = normalise_type_and_config(
                ConnectorType.DATABASE_URL, vault.decrypt_credentials(r["config_encrypted"]))
        except Exception as e:
            logger.warning("[source-catalogs] connection %s stays database_url: %s", r["id"], e)
            continue
        await conn.execute(
            "UPDATE connector_connections SET connector_type = $1, config_encrypted = $2 WHERE id = $3",
            kind.value, vault.encrypt_credentials(config), r["id"])
        await conn.execute(
            "UPDATE data_catalogs SET config = config || jsonb_build_object('connector_type', $1::text) "
            "WHERE kind = 'trino_source' AND config->>'connection_id' = $2",
            kind.value, str(r["id"]))
        logger.info("[source-catalogs] connection %s rewritten as %s", r["id"], kind.value)
        rewritten += 1
    return rewritten


async def ensure_rows(pool) -> int:
    """Register every Trino-engine connection that has no registry row yet — the
    upgrade and disaster-recovery path. Returns how many were added. Legacy
    `database_url` rows are rewritten first (`rewrite_legacy_rows`)."""
    added = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            await rewrite_legacy_rows(conn)
            for r in await conn.fetch(_UNREGISTERED):
                if not is_trino_type(r["connector_type"]):
                    continue
                slug = await register(conn, connection_id=str(r["id"]), name=r["name"],
                                      connector_type=r["connector_type"])
                await sync_grants(conn, str(r["id"]))
                logger.info("[source-catalogs] registered %s for connection %s", slug, r["id"])
                added += 1
    return added
