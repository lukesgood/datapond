# DataPond Portability and Exit Strategy

## Goal

DataPond should let an operator change storage, PostgreSQL hosting, model provider, catalog/query engine, or Kubernetes environment without rewriting the governed RAG product layer.

Portability is a tested property, not an “open source” label. Running many OSS services can create another form of lock-in and operational cost.

## Portability boundaries

| Asset | Portable boundary | Current move mechanism |
|---|---|---|
| Source/object data | S3 API | S3 copy/sync or compatible object migration |
| App metadata | PostgreSQL | `pg_dump`/restore, snapshot/PITR where supported |
| Vectors | pgvector columns | PostgreSQL backup/restore when embedding model is unchanged |
| Tables | Parquet + Apache Iceberg | Copy objects, rewrite/register metadata as needed |
| Models | LiteLLM logical names | Change provider mapping and credentials |
| Identity | JWT/LDAP/WebAuthn/OIDC | Reconfigure issuer/directory; export local state with PostgreSQL |
| Deployment | OCI + Helm + Kubernetes | Apply profile/values to target cluster |
| APIs | REST/OpenAPI | Keep clients independent of provider implementation |

## Current exit paths

### S3 to another object store

1. Freeze or record writes.
2. Copy all object versions required by the recovery policy.
3. Verify count, byte size, checksums, and representative reads.
4. Change the object endpoint/credentials.
5. Rewrite stored source URIs only where the bucket/path changed.

S3-compatible does not guarantee every lifecycle, IAM, versioning, or consistency behavior is identical. Test the target.

### Aurora to PostgreSQL

1. Check PostgreSQL major version and installed extensions.
2. Take a consistent dump/snapshot.
3. Restore roles, schema, data, and `vector` extension.
4. Restore the same `ENCRYPTION_KEY` before starting the backend.
5. Validate collection/chunk counts, indexes, authentication, and credential decryption.

### Bedrock to another model provider

1. Preserve logical names (`embed`, `chat`, `rerank`).
2. Reconfigure LiteLLM mappings and credentials.
3. Run chat, streaming, timeout, and fallback conformance tests.
4. If embedding model or dimension changes, create a new embedding version and re-embed collections.
5. Compare retrieval and citation quality against a fixed evaluation set.

Store model name, provider/version, dimension, content hash, and embedding time with vector data when extending the schema.

### Glue/Athena to Polaris/Trino

1. Copy or retain the same Iceberg object data.
2. Export table namespace, metadata location, and property inventory.
3. Register tables in the Iceberg REST/Polaris catalog.
4. Rewrite warehouse URIs if object locations changed.
5. Translate provider-specific SQL with SQLGlot where practical.
6. Compare schema, snapshots, row counts, and representative queries.

Not every Athena/Glue feature maps directly to Trino/Polaris. Provider-specific grants, workgroups, and query history are control-plane state and require separate handling.

## Critical non-portable state

- `ENCRYPTION_KEY`: mandatory to decrypt stored credentials.
- external provider credentials and IAM policies.
- DNS/TLS and environment-specific ingress configuration.
- AWS-specific alarms, schedules, and service settings.
- Iceberg metadata URIs if warehouse paths change.
- embeddings when provider/model/dimension changes.

Keep these in an explicit environment manifest and secure secret backup.

## Export bundle design

A future portable export should contain:

```text
manifest.json
postgres/
  schema.sql
  data.dump
catalog/
  tables.json
  iceberg-metadata-locations.json
models/
  logical-model-mapping.yaml
policies/
  collections.json
  sharing.json
  table-policies.json
lineage/
  events.jsonl
checksums/
  objects.sha256
```

Secrets should not be included by default. Export references and rebind them on import.

Proposed CLI—**roadmap, not currently implemented**:

```bash
datapond export --output s3://backup/export/ --include catalog,policies,collections,lineage,model-config
datapond import --source s3://backup/export/ --catalog iceberg-rest --query-engine trino
```

## Exit drill

Run at least quarterly for production environments.

1. Restore PostgreSQL into an isolated target.
2. Copy a representative object/Iceberg dataset.
3. Rebind to a different object endpoint or account.
4. Rebind logical model names to a different provider; re-embed a test collection if required.
5. Register representative tables in an alternate catalog, if table workflows are used.
6. Verify authentication, collection access, PII masking, citations, usage attribution, and audit.
7. Record RPO, RTO, data mismatches, provider-specific blockers, and remediation.

## Acceptance criteria

- No customer object or PostgreSQL state is accessible only through a proprietary DataPond format.
- Core Knowledge APIs run after provider rebinding.
- Restored credentials decrypt with the preserved encryption key.
- Collection and chunk counts match.
- RAG evaluation remains within an agreed quality tolerance.
- Optional table schemas, snapshots, and representative row counts match.
- The operator can identify all remaining provider-specific resources.

## Open-core policy

Data export, provider rebinding, and migration documentation belong in Community. Enterprise may provide orchestrated multi-environment migration, policy packs, verified tools, and support, but should not block access to customer data.

## Roadmap

- versioned `datapond export/import`
- provider conformance test suite
- OpenLineage-compatible durable event export
- Glue ↔ Iceberg REST registration automation
- embedding version migration workflow
- automated quarterly exit drill
- documented cross-cloud reference profile
