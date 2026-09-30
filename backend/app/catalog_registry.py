"""Which data catalogs DataPond reads, and how a table is named across them.

The `data_catalogs` table (migration 0018) is the source of truth. Until it has a row
— a fresh install before startup seeded it, a database that cannot be reached, a unit
test — the registry is one entry derived from today's env, so a single-catalog
deployment behaves exactly as it did before the registry existed.

Reads are synchronous and never do IO: the catalog readers, the table resolver and the
RLS engine run on request threads and inside `asyncio.to_thread`. The database is read
by `load()` — at startup and on a short interval by `run_refresher()` — and the rows it
returns are what every synchronous caller sees. A database that stops answering keeps
the last rows it gave, rather than falling back to env mid-flight and changing what a
two-part table name means.

A catalog's `name` is the registry key; `engine_catalog` is what the query engine calls
it and what SQL carries. For the default entry the two are the same value — the one
`rls_policies.catalog_name` already stores — and `resolve()` accepts either.
"""
import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

KINDS = ("glue", "iceberg_rest", "polaris")
CACHE_TTL_SECONDS = 30

_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


class UnknownCatalog(ValueError):
    """A catalog name that is not an enabled registry entry."""


# ── config: what each kind may carry ─────────────────────────────────────────
#
# `config` is non-secret and returned to every reader of GET /api/catalogs, so the keys
# are a whitelist per kind: anything not named here — a `credential`, a `token`, a
# `header.Authorization` — is refused rather than stored where it would be shown.
# Credentials go through `secret` (stored encrypted, see SECRET_PREFIX).

CONFIG_KEYS = {
    "glue": {"region": str, "catalog_id": str, "warehouse": str, "via_rest": bool,
             "role_arn": str, "external_id": str},
    "iceberg_rest": {"uri": str, "warehouse": str, "sigv4": bool, "signing_name": str,
                     "signing_region": str, "scope": str, "prefix": str},
    "polaris": {"warehouse": str, "uri": str},
}

_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
_ACCOUNT = re.compile(r"^\d{12}$")
_SIGNING_NAME = re.compile(r"^[a-z0-9-]{1,64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# Plain http only reaches a catalog inside the cluster (or on the developer's machine):
# a bearer token or client secret sent over http anywhere else is a leaked one.
_IN_CLUSTER_SUFFIXES = (".svc", ".svc.cluster.local")


def check_uri(uri: str) -> str:
    """An https URL, or http to an in-cluster service / localhost. Never one that
    carries credentials — the URL is config, and config is shown."""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(uri)
        host = (parts.hostname or "").lower()
    except ValueError:
        raise ValueError(f"uri is not a URL: {uri!r}")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValueError("uri must not carry credentials; put them in the secret.")
    if not host:
        raise ValueError(f"uri has no host: {uri!r}")
    if parts.scheme == "https":
        return uri
    if parts.scheme == "http" and (host == "localhost" or host.endswith(_IN_CLUSTER_SUFFIXES)):
        return uri
    raise ValueError("uri must be https (http only for *.svc, *.svc.cluster.local or "
                     "localhost).")


def validate_config(kind: str, config: Optional[dict]) -> dict:
    """The config as given, or ValueError naming what is wrong with it."""
    if kind not in CONFIG_KEYS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
    config = dict(config or {})
    allowed = CONFIG_KEYS[kind]
    for key, value in config.items():
        if key not in allowed:
            raise ValueError(f"config key '{key}' is not allowed for {kind}; allowed: "
                             f"{', '.join(sorted(allowed))}. Credentials go in the secret.")
        want = allowed[key]
        if not isinstance(value, want):
            raise ValueError(f"config '{key}' must be a "
                             f"{'boolean' if want is bool else 'string'}.")
        if want is str and (len(value) > 512 or _CONTROL.search(value)):
            raise ValueError(f"config '{key}' must be at most 512 printable characters.")
    if config.get("region") and not _REGION.match(config["region"]):
        raise ValueError(f"region is not an AWS region: {config['region']!r}")
    if config.get("signing_region") and not _REGION.match(config["signing_region"]):
        raise ValueError(f"signing_region is not an AWS region: {config['signing_region']!r}")
    if config.get("catalog_id") and not _ACCOUNT.match(config["catalog_id"]):
        raise ValueError("catalog_id must be a 12-digit AWS account id.")
    if config.get("signing_name") and not _SIGNING_NAME.match(config["signing_name"]):
        raise ValueError("signing_name must be an AWS service name such as glue or s3tables.")
    if config.get("uri"):
        check_uri(config["uri"])
    if kind == "iceberg_rest":
        if not config.get("uri"):
            raise ValueError("iceberg_rest needs a uri.")
        if config.get("sigv4") and not (config.get("signing_name")
                                        and config.get("signing_region")):
            raise ValueError("sigv4 needs signing_name and signing_region.")
    if config.get("external_id") and not config.get("role_arn"):
        raise ValueError("external_id needs a role_arn.")
    if config.get("role_arn"):
        from app.aws_assume_role import validate_role
        validate_role(config["role_arn"], config.get("external_id"))
    if kind == "glue" and config.get("via_rest"):
        if not (config.get("region") and config.get("catalog_id")):
            raise ValueError("glue via_rest needs region and catalog_id (the account id "
                             "whose catalog is read).")
    return config


# ── secrets ──────────────────────────────────────────────────────────────────
#
# A catalog's credential is a system_settings row, encrypted with the same vault as
# connector credentials and AI keys; `secret_ref` names the row. load() reads the
# ciphertext alongside the registry, so a reader built on a request thread never does
# IO for it, and plaintext exists only while a catalog client is being built.

SECRET_PREFIX = "catalog_secret."
_secrets: dict = {}


def secret_ref_for(name: str) -> str:
    return f"{SECRET_PREFIX}{name}"


def set_secret_ciphertext(ref: str, ciphertext: Optional[str]) -> None:
    if ciphertext:
        _secrets[ref] = ciphertext
    else:
        _secrets.pop(ref, None)


def secret_for(entry: "CatalogEntry") -> Optional[str]:
    """The entry's credential in plaintext, or None. Never logged."""
    ref = getattr(entry, "secret_ref", None)
    if not ref or ref not in _secrets:
        return None
    try:
        from app.connectors.vault import CredentialVault
        return CredentialVault().decrypt_credentials(_secrets[ref]).get("v") or None
    except Exception:
        logger.warning("[catalogs] secret for %s cannot be decrypted", entry.name)
        return None


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    kind: str
    engine_catalog: str
    config: dict = field(default_factory=dict, compare=False, hash=False)
    secret_ref: Optional[str] = None
    is_default: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class TableRef:
    """One table, named the way the engine names it: catalog.namespace.table.

    A bare name parses to catalog=None, namespace=None — the table resolver decides
    which catalog and namespace it means, and refuses when it could mean several.
    Two parts mean the default catalog.
    """
    catalog: Optional[str]
    namespace: Optional[str]
    table: str

    @classmethod
    def parse(cls, text: str, default: Optional[str] = None) -> "TableRef":
        parts = str(text or "").strip().split(".")
        if not 1 <= len(parts) <= 3 or not all(_IDENT.match(p or "") for p in parts):
            raise ValueError(
                f"Not a table name: {text!r} — expected table, namespace.table or "
                f"catalog.namespace.table, each a bare identifier.")
        if len(parts) == 1:
            return cls(None, None, parts[0])
        if len(parts) == 2:
            return cls(default or default_entry().engine_catalog, parts[0], parts[1])
        return cls(parts[0], parts[1], parts[2])

    def sql(self) -> str:
        return ".".join(p for p in (self.catalog, self.namespace, self.table) if p)

    def key(self) -> str:
        return self.sql().lower()


# ── the env-derived default ──────────────────────────────────────────────────

def env_default_entry() -> CatalogEntry:
    """The one catalog today's env describes. Computed on every call — tests and
    Settings change env at runtime, and this costs nothing."""
    backend = os.getenv("ICEBERG_CATALOG_BACKEND", "polaris").strip().lower()
    # The engine names the catalog. An unset QUERY_ENGINE on the glue backend is the
    # Athena reference (Helm derives one from the other).
    engine = (os.getenv("QUERY_ENGINE") or ("athena" if backend == "glue" else "trino"))
    if engine.strip().lower() == "athena":
        name = "AwsDataCatalog"
    else:
        name = (os.getenv("TRINO_CATALOG") or "iceberg").strip() or "iceberg"
    if backend == "glue":
        config = {"warehouse": os.getenv("GLUE_WAREHOUSE", "")}
        region = os.getenv("S3_REGION")
        if region:
            config["region"] = region
        kind = "glue"
    else:
        # The Polaris catalog this entry lists. Other Polaris catalogs are other rows.
        config = {"warehouse": os.getenv("POLARIS_WAREHOUSE", "iceberg") or "iceberg"}
        uri = os.getenv("POLARIS_URI")
        if uri:
            config["uri"] = uri
        kind = "polaris"
    return CatalogEntry(name=name, kind=kind, engine_catalog=name, config=config,
                        is_default=True, enabled=True)


# ── the cache ────────────────────────────────────────────────────────────────

_state = {"entries": None, "at": 0.0}


def reset() -> None:
    """Forget what the database said; the env default stands in again."""
    _state["entries"] = None
    _state["at"] = 0.0
    _secrets.clear()


def set_entries(entries: List[CatalogEntry]) -> None:
    """Install rows as if the database had returned them (load() and tests)."""
    _state["entries"] = list(entries) if entries else None
    _state["at"] = time.monotonic()


def entries(include_disabled: bool = False) -> List[CatalogEntry]:
    rows = _state["entries"]
    if not rows:
        return [env_default_entry()]
    return [e for e in rows if include_disabled or e.enabled]


def default_entry() -> CatalogEntry:
    enabled = entries()
    for e in enabled:
        if e.is_default:
            return e
    return enabled[0] if enabled else env_default_entry()


def cached_default_name() -> Optional[str]:
    """The default entry's SQL name, only when the database supplied it. None means
    "not known" — the caller keeps its own env fallback. Never does IO."""
    if not _state["entries"]:
        return None
    return default_entry().engine_catalog


def resolve(name: Optional[str] = None) -> CatalogEntry:
    """The enabled entry `name` refers to — by registry name or engine catalog name,
    case-insensitively (SQL identifiers are). None or "" is the default."""
    if name is None or str(name).strip() == "":
        return default_entry()
    wanted = str(name).strip()
    if not _IDENT.match(wanted):
        raise UnknownCatalog(f"Not a catalog name: {name!r}")
    low = wanted.lower()
    enabled = entries()
    for e in enabled:
        if e.name.lower() == low:
            return e
    for e in enabled:
        if e.engine_catalog.lower() == low:
            return e
    known = ", ".join(e.name for e in enabled) or "(none)"
    raise UnknownCatalog(f"Unknown catalog '{wanted}'. Known catalogs: {known}.")


def is_default(name: Optional[str]) -> bool:
    """True when `name` is empty or refers to the default entry."""
    if name is None or str(name).strip() == "":
        return True
    d = default_entry()
    low = str(name).strip().lower()
    return low in (d.name.lower(), d.engine_catalog.lower())


# ── the database ─────────────────────────────────────────────────────────────

_SELECT = """SELECT name, kind, engine_catalog, config, secret_ref, is_default, enabled
               FROM data_catalogs
              ORDER BY is_default DESC, name"""


_SECRETS = "SELECT key, value FROM system_settings WHERE key = ANY($1::text[])"


def _row_to_entry(r) -> CatalogEntry:
    cfg = r["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg or "{}")
    return CatalogEntry(name=r["name"], kind=r["kind"], engine_catalog=r["engine_catalog"],
                        config=dict(cfg or {}), secret_ref=r["secret_ref"],
                        is_default=bool(r["is_default"]), enabled=bool(r["enabled"]))


async def load(pool, *, force: bool = False, timeout: float = 5.0) -> List[CatalogEntry]:
    """Read the registry from the database when the cache is stale (or `force`).

    Never raises. An empty table leaves the env default in place; an unreachable
    database keeps whatever rows were last read.
    """
    fresh = _state["entries"] is not None and \
        (time.monotonic() - _state["at"]) < CACHE_TTL_SECONDS
    if fresh and not force:
        return entries()
    try:
        async def _fetch():
            async with pool.acquire() as c:
                return await c.fetch(_SELECT)
        rows = await asyncio.wait_for(_fetch(), timeout=timeout)
        loaded = [_row_to_entry(r) for r in rows]
        refs = [e.secret_ref for e in loaded if e.secret_ref]
        try:
            fetched = {}
            if refs:
                async def _fetch_secrets():
                    async with pool.acquire() as c:
                        return await c.fetch(_SECRETS, refs)
                fetched = {r["key"]: r["value"]
                           for r in await asyncio.wait_for(_fetch_secrets(), timeout=timeout)}
            # Replaced, not merged: a cleared or deleted secret must stop being used.
            _secrets.clear()
            _secrets.update({k: v for k, v in fetched.items() if v})
        except Exception as e:
            logger.warning("[catalogs] catalog secrets not read, keeping last: %s", e)
        set_entries(loaded)
    except Exception as e:
        logger.warning("[catalogs] registry read failed, keeping %s: %s",
                       "last rows" if _state["entries"] else "env default", e)
    return entries()


_SEED = """INSERT INTO data_catalogs (name, kind, engine_catalog, config, is_default, enabled)
           SELECT $1, $2, $3, $4::jsonb, true, true
            WHERE NOT EXISTS (SELECT 1 FROM data_catalogs)
           ON CONFLICT DO NOTHING"""


async def seed_from_env(pool) -> None:
    """Write the env default as the first row of an empty registry. Idempotent: a
    registry with any row — including one an admin edited — is left alone."""
    e = env_default_entry()
    async with pool.acquire() as c:
        await c.execute(_SEED, e.name, e.kind, e.engine_catalog, json.dumps(e.config))


async def run_refresher(pool, interval: float = CACHE_TTL_SECONDS) -> None:
    """Keep the cache within one interval of the table. Runs for the process lifetime."""
    while True:
        await load(pool, force=True)
        await asyncio.sleep(interval)
