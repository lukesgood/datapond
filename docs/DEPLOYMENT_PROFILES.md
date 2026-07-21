# DataPond Deployment Profiles

Helm profile names are retained for compatibility. Product role, actual topology, and enabled capabilities are defined here.

## Selection summary

| Profile | Choose when | Avoid when |
|---|---|---|
| Portable Core · AWS | You need the smallest S3/Bedrock governed RAG starter | You need Catalog/SQL workflows out of the box |
| AWS Single-Node Reference | You want the current end-to-end AWS Terraform + Helm reference | You require application-node HA or EKS |
| AWS Hybrid Extended | You already operate Kubernetes and intentionally want AWS endpoints plus OSS engines | You expect a lean or automatically provisioned EKS stack |
| Sovereign OSS Extended | You need local control and are prepared to operate the add-ons | You want the lowest operational burden |
| Development/Quick Test | Local and integration validation | Production |
| Self-Hosted Extended compatibility | You maintain the legacy full stack | New AWS deployments |

## Profile matrix

| Values file | Runtime label | Core database | Object/model | Catalog/query | Optional stack | Maturity |
|---|---|---|---|---|---|---|
| `values-foundation.yaml` | Portable Core · AWS | in-cluster PostgreSQL/pgvector | S3 + Bedrock | none | disabled | supported starter |
| `values-prod-single.yaml` | AWS Single-Node Reference | Aurora PostgreSQL/pgvector | S3 + Bedrock | Glue + Athena | heavy add-ons disabled | reference |
| `values-aws.yaml` | AWS Hybrid Extended | external PostgreSQL | S3 + Bedrock | inherited Polaris/Trino unless overridden | inherited base defaults | compatibility |
| `values-onprem.yaml` | Sovereign OSS Extended | in-cluster PostgreSQL/pgvector | S3-compatible + local model path | Polaris + Trino | selected full OSS | community |
| `values-dev.yaml` | Development | in-cluster | self-hosted | base/overrides | enabled for development | development |
| `values-quicktest.yaml` | Quick Test | in-cluster | self-hosted | base/overrides | reduced resources | development |
| `values-prod.yaml` | Self-Hosted Extended | in-cluster replicated config | self-hosted | base full stack | high resource | compatibility |

## Portable Core · AWS starter

File: `helm/datapond/values-foundation.yaml`

Runs approximately five workloads:

- backend
- frontend
- PostgreSQL + pgvector
- LiteLLM
- Valkey

Uses native S3 and Bedrock. It explicitly disables Trino, Spark, Polaris, Airflow, MLflow, RisingWave, OpenMetadata, Jupyter, Ollama, vLLM, and in-cluster MinIO.

This profile does **not** set `catalog.backend: glue`. Therefore Sources/Catalog/SQL Lab are hidden. It is a governed RAG profile, not a complete managed lakehouse.

## AWS Single-Node Reference

File: `helm/datapond/values-prod-single.yaml`

Terraform + Helm topology:

- one EC2 Spot/K3s application node
- external Aurora PostgreSQL Serverless v2
- native S3
- Glue Data Catalog and Athena output/workgroup configuration
- Bedrock through LiteLLM
- ECR image repositories
- Route53 + TLS
- Secrets Manager recovery vault
- CloudWatch/SNS integration

This is the closest current profile to an AWS-managed data plane. Its availability model is **single application node + fast restore**, not EKS/HA.

Follow [DEPLOY_SINGLE_NODE.md](DEPLOY_SINGLE_NODE.md).

## AWS Hybrid Extended compatibility

File: `helm/datapond/values-aws.yaml`

This overlay:

- configures native S3;
- configures Bedrock model mappings;
- disables in-cluster PostgreSQL and expects an external database;
- disables Ollama/vLLM;
- otherwise inherits the base chart's heavy OSS defaults.

It does not create EKS, Aurora, S3, or other AWS resources. An operator must bring infrastructure and explicitly review every inherited component. Do not use it as shorthand for “AWS managed profile.”

## Sovereign OSS Extended

File: `helm/datapond/values-onprem.yaml`

This profile prioritizes control and disconnected/local operation. It can run local object storage, model gateway/provider, catalog, query, streaming, metadata, notebook, and pipeline services.

Recommendations:

1. Start from the core and disable unnecessary add-ons.
2. Size for the services actually enabled; the full profile targets 32 GB+ RAM.
3. Review [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
4. Use an HA storage class and external backup system before production use.
5. Test local model embedding dimensions against existing collections.

## Runtime identity

Every maintained profile sets:

```yaml
product:
  profile:
    id: portable-core-aws
    label: Portable Core · AWS
    description: ...
    maturity: supported-starter
    topology: kubernetes
```

The backend publishes this as non-secret capability metadata. It is informational only. Actual component flags determine features.

## Compatibility rules

- Existing values filenames and release commands remain valid.
- Existing flat `/api/capabilities` booleans remain valid.
- Profile metadata may be overridden for a custom deployment, but this never enables a capability.
- Optional menus require explicit boolean `true`; loading or fetch failure does not expose them.
- Base `values.yaml` is the OSS extended chart default, not the recommended production profile.

## Roadmap profiles

The following profiles do not exist today:

- EKS + managed node group/auto mode reference
- multi-AZ application-node HA reference
- EMR Serverless/S3 Tables/Lake Formation data plane
- AOSS vector profile
- DataZone governance profile
- AWS Marketplace installer/billing profile

Add them only after infrastructure code, Helm wiring, security review, and live acceptance are present.
