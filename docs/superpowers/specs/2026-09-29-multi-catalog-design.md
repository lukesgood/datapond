# Multi-catalog: a catalog registry and three-part table identity

Status: design, 2026-09-29. Premise from the product owner: DataPond is to be a
general-purpose product, so a customer with more than one data catalog — several Glue
catalogs across accounts, S3 Tables, several Polaris catalogs, Unity Catalog or Snowflake
Open Catalog over Iceberg REST — must work, not only the single catalog of the AWS
reference.

## 1. Where it breaks today

A survey of the code (2026-09-29) found ~60 places that assume one catalog. The catalog
backend is one env switch (`ICEBERG_CATALOG_BACKEND`) and one pyiceberg singleton; the
engine has one `default_catalog` (`iceberg` on Trino, `AwsDataCatalog` on Athena); most
identifiers are `(namespace, table)`. Only the RLS/masking policy tables and engine are
three-part.

Ten of those places would **silently return wrong data** with a second catalog:

1. `PolarisCatalogReader.list_namespaces/list_tables` merge every Polaris catalog into
   one list (feeds the resolver index, schema tree, coverage, PII scan, AI context).
2. `qualify_tables` adds only the namespace; a bare name found in catalog B executes
   against the session catalog A, and its RLS key is `A.ns.t`, so B's policy does not
   apply — the query runs unfiltered.
3. RLS `_qualify` pads two-part names with the one default catalog.
4. `rls_coverage` stamps every table with the env catalog.
5. `/catalog/columns`, `/catalog/tables/{ns}/{t}`, `/preview` accept `catalog` and ignore it.
6. `get_catalog_schemas` and `/catalog/tables` label every table with the default.
7. `catalog_graph`, `plan_review`, the assistant's query preview drop the catalog.
8. Knowledge bridge: sink invalidation and lineage match on `(namespace, table)`;
   `_read_iceberg_docs` always reads the engine prefix.
9. `query_history.catalog` records the default, not the catalog used.
10. The Analytics schema tree drops the catalog on insert; the Knowledge picker picks
    the catalog named `iceberg` or the first.

And one defect that is wrong **today**, with one catalog: connector writers never pass
the target namespace, so every sync lands in `default` while the job records the
configured target.

## 2. Decisions

1. **The registry is the source of truth.** A `data_catalogs` table (name, kind,
   engine catalog, non-secret config, secret reference, default flag, enabled). Helm
   seeds the default entry from today's settings on first start; an existing
   deployment keeps working with no action.
2. **A catalog's name is the name SQL uses for it.** The default entry is named
   `AwsDataCatalog` on Athena and `iceberg` on Trino — exactly the value
   `rls_policies.catalog_name` already holds — so every stored policy keeps matching.
3. **`TableRef(catalog, namespace, table)` everywhere.** Two-part input resolves to the
   default catalog; a bare name resolves across all enabled catalogs and is an error
   when it matches more than one.
4. **Iceberg REST is the primary integration.** One reader covers Polaris, Unity
   Catalog, Snowflake Open Catalog, Nessie and S3 Tables; a Glue reader stays for Glue
   catalog ids, cross-account roles and Lake Formation resource links. (Glue's own
   Iceberg REST endpoint and pyiceberg's handling of resource links are unverified and
   are measured before P2 relies on them.)
5. **Execution stays with the engine.** DataPond reads metadata per catalog and governs;
   queries across catalogs are executed by Trino catalogs or Athena data catalogs bound
   in the registry (`engine_catalog`). No federation engine of our own.
6. **DataPond consumes catalogs; it does not become one.** No lineage, glossary or
   ownership management — that would compete with Unity Catalog / DataZone and break
   the v6 "not doing" line.
7. **Writes stay on the default catalog** until a customer needs otherwise; the
   connector namespace defect is fixed regardless.

## 3. Phases

| Phase | Scope | Size |
|---|---|---|
| **P1 identity and registry** | `data_catalogs` + seed; `TableRef`; readers bound to a registry entry (Polaris no longer merged); resolver index keyed by `(catalog, namespace)` with cross-catalog ambiguity errors and catalog-qualified rewrites for non-default catalogs; catalog API/columns/preview/tables honour and return the catalog; schema tree per catalog; RLS coverage per catalog; relationship graph three-part ids; Knowledge `SourceIngest.catalog`, sink and lineage keyed with catalog; chat `TableRef.catalog`; frontend passes the catalog through (detail page, Analytics insert, Knowledge picker); connector writer namespace fix | ~1 week |
| **P2 many readers** | Iceberg REST reader; Glue reader with catalog id / assume-role; admin CRUD API + UI for catalogs; engine binding (Helm renders one Trino catalog per registry entry; Athena data catalog names); per-catalog health in Services | 1–1.5 weeks |
| **P3 access and tools** | Per-caller catalog grants (listing filter + table-reference check on the query path); `catalog` on MCP/REST tool parameters; audit rows carry the catalog | ~1 week |
| **P4 proof** | CI installs two Polaris catalogs plus one of another kind; measured S3 Tables, Unity Catalog, cross-account Glue | ~0.5 week |

## 4. Compatibility

- One catalog configured: every response keeps its shape plus a `catalog` field; SQL
  that names two parts is left byte-for-byte unchanged; bare names are rewritten to
  two parts as before (the default catalog is the engine's session catalog).
- Stored `refresh_source` / sink rows without a catalog mean the default catalog.
- Relationship node ids become three-part; the frontend reads both shapes.
