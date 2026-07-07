# AWS MVP Runbook — Bedrock RAG on S3 + Aurora pgvector

## 0. Prerequisites
- `terraform apply` complete (Tasks 4-5); Bedrock model access enabled.
- Instance profile `datapond-app-profile` attached to the K3s EC2 instance.

### Bedrock Credentials

LiteLLM connects to Bedrock for embeddings (Titan) and generation (Claude). Credential wiring depends on deployment mode:

- **EC2 / K3s PoC**: No config needed — instance profile `datapond-app-profile` is auto-assumed via metadata service.
- **EKS**: Use IRSA: `terraform apply -var eks_oidc_provider_arn=... -var eks_oidc_provider_url=...`, then `helm upgrade ... --set litellm.serviceAccount.roleArn=$(terraform output -raw litellm_bedrock_role_arn)`.
- **Portable / Static**: Set `litellm.aws.staticCredentials=true` and add `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` to `datapond-secrets` Secret.

**Required:** Bedrock model access must be enabled in the AWS console per region (Claude Haiku/Sonnet + Titan Embed v2). See [AWS Bedrock Setup Guide](./AWS_BEDROCK_SETUP.md) for detailed instructions.

## 1. Seed credentials secret (Aurora) and deploy
    kubectl -n datapond create secret generic datapond-secrets \
      --from-literal=POSTGRES_USER=datapond \
      --from-literal=POSTGRES_PASSWORD=<db_master_password> \
      --from-literal=POSTGRES_DB=datapond \
      --from-literal=JWT_SECRET=<random> \
      --from-literal=INTERNAL_API_KEY=<random> \
      --dry-run=client -o yaml | kubectl apply -f -

    # (the S3 bucket is specified per-request in /ingest-source, not via Helm)
    helm upgrade --install datapond helm/datapond -n datapond \
      -f helm/datapond/values-aws.yaml \
      --set externalDatabase.host=<aurora_endpoint>

## 2. Wait for backend ready
    kubectl -n datapond rollout status deploy/backend
    kubectl -n datapond logs deploy/backend | grep -i "vector schema"   # ensure_vector_schema ran

## 3. Upload sample source docs to S3
    aws s3 cp ./samples/ s3://<bucket_name>/rag-samples/ --recursive   # *.md / *.txt

## 4. End-to-end RAG smoke test
    TOKEN=$(curl -s -X POST https://<domain>/api/auth/login \
      -d '{"username":"admin","password":"<pw>"}' -H 'Content-Type: application/json' | jq -r .access_token)

    # create collection
    curl -s -X POST https://<domain>/api/ai/collections -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' -d '{"name":"mvp","description":"aws mvp"}'

    # ingest from S3 (uses IAM role; embeds via Bedrock Titan)
    curl -s -X POST https://<domain>/api/ai/collections/mvp/ingest-source \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
      -d '{"type":"s3","bucket":"<bucket_name>","prefix":"rag-samples/","max_files":50}'
    # expect: {"success":true,"documents":N,"chunks":M,...}

    # RAG query (generation via Bedrock Claude)
    curl -s -X POST https://<domain>/api/ai/rag -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' \
      -d '{"collection":"mvp","question":"<a question answerable from the docs>","k":5}'
    # expect: {"answer":"... [1] ...","citations":[...],"has_ai":true}

## 5. Pass criteria
- ingest-source returns documents > 0 and chunks > 0 (Titan embeddings succeeded).
- /api/ai/rag returns has_ai=true with non-empty citations referencing s3://<bucket> sources.
- backend logs show no 502 from embeddings and no egress-policy 403.

## 6. Local / on-prem object storage (MinIO)
On non-AWS profiles (`values-dev`, `values-quicktest`, `values-onprem`, `values-prod`)
the in-cluster S3 store is **MinIO** (it replaced SeaweedFS). The AWS profile
(`values-aws`) sets `minio.enabled: false` and uses native S3 instead.

- S3 API: `http://minio:9000` (what Trino/Spark/Polaris/RisingWave/MLflow/Jupyter/backend point at)
- Console UI: `http://minio:9001` (exposed via ingress when `minio.enabled`)
- Buckets: the `iceberg` warehouse bucket is created by the `minio-bucket-init` Job
  (post-install/upgrade hook).
- Credentials: `minio.auth.rootUser` / `minio.auth.rootPassword` (per profile).
- `minio.clusterIP` must be a static service IP in your cluster's service CIDR
  (used by the CoreDNS virtual-host rewrite). Set per environment.

## 7. Critical secrets (auto-generated + preserved)
`JWT_SECRET`, `INTERNAL_API_KEY`, `ENCRYPTION_KEY`, and `ADMIN_PASSWORD` are
generated automatically by Helm on first install (no manual seeding needed —
step 1's `--from-literal=JWT_SECRET=...`/`INTERNAL_API_KEY=...` are only
required if you're bootstrapping the secret out-of-band before `helm upgrade
--install`). On every subsequent `helm upgrade`, the chart looks up the
existing in-cluster `datapond-secrets` Secret and preserves these values —
they are never silently rotated. `ENCRYPTION_KEY` in particular must never
change once set: it encrypts stored credentials (connector secrets, provider
keys), and rotating it makes them undecryptable.

**Pre-upgrade preflight (existing deployments only):** if your running backend
got its `ENCRYPTION_KEY` out-of-band (hand-edited Secret under a different key
name, or a raw Deployment env — the live EC2 deploy predates chart-managed
generation), you MUST copy that working key into `datapond-secrets` under
exactly `ENCRYPTION_KEY` **before** the first `helm upgrade` onto this chart.
Otherwise Helm generates a fresh key and previously stored encrypted settings
(provider API keys, connector credentials) silently become undecryptable.
Check first:

    kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.ENCRYPTION_KEY}' | base64 -d
    # empty? seed it with the value your running backend currently uses:
    kubectl -n datapond patch secret datapond-secrets --type merge \
      -p '{"stringData":{"ENCRYPTION_KEY":"<the-live-key>"}}'

Retrieve the generated initial admin password:

    kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d

To pin the admin password instead of using the generated one, set
`auth.adminPassword` in your values file before first install.

Production (`values-aws.yaml`, `values-onprem.yaml`, `values-prod.yaml`)
fails closed at backend startup if `JWT_SECRET`, `ENCRYPTION_KEY`, or
`ADMIN_PASSWORD` are missing — a Helm deploy always provides them, so this
should only trip if the Secret was hand-edited or deployed outside Helm.

## Component passwords (P0-1b)
POSTGRES_PASSWORD, MinIO S3_SECRET_KEY, AIRFLOW_PASSWORD, JUPYTER_TOKEN, POLARIS_CLIENT_SECRET
are auto-generated on first install and preserved across upgrades (lookup-preserve).
Retrieve any of them:

    kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.<KEY>}' | base64 -d

⚠️ **NEVER delete datapond-secrets while keeping data PVCs:** Postgres/MinIO were initialized
with the generated passwords — a regenerated Secret will not match the data volumes and
every component login will fail. Delete the Secret only together with the PVCs (full reset).
Existing installs keep their current passwords (no rotation is performed by upgrades).
If catalog auth starts failing with 401 after an upgrade (POLARIS_CLIENT_SECRET desync),
recover by re-running the Polaris bootstrap with the current POLARIS_CLIENT_SECRET (delete
the /shared/skip sentinel-guarded state only with care) — or restore the previous secret
value into datapond-secrets.

## 8. Live EC2 deploy — tar-sync caveat

The live EC2 (K3s) deployment is updated via an SSM tar-sync pipeline, not a full git
checkout — `/home/ubuntu/datapond` only contains whatever was last synced. Any new
runtime file (routes, schema, config) must be added to the tar-sync set or it never
reaches the built image. **`ee/` must be included in the tar-sync set** — the enterprise
image build COPYs `ee/backend/ee`; a sync that omits `ee/` silently produces a community
image (no SSO endpoints, no error). This does not affect a fresh install via
`helm/install.sh`, which always builds from a full checkout.
