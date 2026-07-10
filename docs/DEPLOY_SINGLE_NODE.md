# Deploying DataPond — Single-Node K3s Production (AWS)

This is the end-to-end operator runbook for standing up a **production, customer-facing**
DataPond deployment on a single K3s node in AWS, per
`docs/superpowers/specs/2026-07-10-aws-single-node-production-deployment-design.md`. It
provisions: EC2 (K3s) + Elastic IP, ECR, Aurora Serverless v2 pgvector, S3, a Secrets
Manager DR vault, and a Route53 A record + Let's Encrypt TLS in front of the `foundation`
Helm profile (backend/frontend/valkey/litellm). Heavy analytics (Trino/Spark/Polaris/
Airflow/OpenMetadata) are **not** part of this topology — see the design doc §8 for the
AWS-managed alternative (Athena/EMR Serverless).

Read this top to bottom before starting; the steps are order-dependent (apply infra
before pushing images so the ECR repos exist; on a rebuild, re-seed secrets before the
app connects to a restored Aurora — see step 4's two paths).

---

## 1. Prerequisites

Before touching Terraform, have these ready:

1. **A Route53 hosted zone for your domain.** You need the zone ID (`Z...`) and the
   domain/subdomain the app will live at, e.g. `datapond.example.com`. The zone can be
   one you already own in this account, or a subdomain delegated to it. `terraform apply`
   creates the A record; it does **not** create the hosted zone itself.
2. **Bedrock model access enabled** in the target account/region (console, one-time,
   per-region). AWS console → Bedrock → Model access → enable:
   - Amazon Titan Text Embeddings V2 (`amazon.titan-embed-text-v2:0`)
   - Anthropic Claude Haiku (`us.anthropic.claude-haiku-4-5-20251001-v1:0`)
   - Anthropic Claude Sonnet (`us.anthropic.claude-sonnet-4-6`)

   See `docs/AWS_BEDROCK_SETUP.md` for details. Without this, litellm's Bedrock calls
   fail with an access-denied error at request time (Terraform apply succeeds regardless
   — this is an account-level gate, not an IAM policy).
3. **An ECR-push OIDC role + the `ECR_PUSH_ROLE_ARN` GitHub secret.** `.github/workflows/
   ecr-push.yml` assumes an AWS IAM role via GitHub's OIDC provider (`id-token: write`) —
   this role is a manual, one-time prerequisite (Terraform does not create it, since it's
   a GitHub↔AWS trust relationship independent of any one environment). One-time setup:
   ```bash
   # 1. Create (or reuse) the GitHub OIDC provider in this account:
   aws iam create-open-id-connect-provider \
     --url https://token.actions.githubusercontent.com \
     --client-id-list sts.amazonaws.com \
     --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

   # 2. Create a role trusting that provider, scoped to this repo:
   cat > ecr-push-trust.json <<'EOF'
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": { "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com" },
       "Action": "sts:AssumeRoleWithWebIdentity",
       "Condition": {
         "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
         "StringLike":   { "token.actions.githubusercontent.com:sub": "repo:<ORG>/<REPO>:*" }
       }
     }]
   }
   EOF
   aws iam create-role --role-name datapond-ecr-push \
     --assume-role-policy-document file://ecr-push-trust.json

   # 3. Grant it ECR push on the two repos (after Task 2's `terraform apply` has created
   #    them — see step 3 below; can also grant `Resource: "*"` up front and narrow later):
   aws iam put-role-policy --role-name datapond-ecr-push --policy-name ecr-push \
     --policy-document '{"Version":"2012-10-17","Statement":[
       {"Effect":"Allow","Action":"ecr:GetAuthorizationToken","Resource":"*"},
       {"Effect":"Allow","Action":["ecr:BatchCheckLayerAvailability","ecr:PutImage",
         "ecr:InitiateLayerUpload","ecr:UploadLayerPart","ecr:CompleteLayerUpload",
         "ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
        "Resource":["arn:aws:ecr:us-east-1:<ACCOUNT_ID>:repository/datapond-backend",
                    "arn:aws:ecr:us-east-1:<ACCOUNT_ID>:repository/datapond-frontend"]}
     ]}'

   # 4. Store the role ARN as a GitHub Actions repo secret:
   gh secret set ECR_PUSH_ROLE_ARN --body "arn:aws:iam::<ACCOUNT_ID>:role/datapond-ecr-push"
   ```
4. **The bootstrap remote-state bucket** (`terraform/bootstrap`), created once per
   account:
   ```bash
   cd terraform/bootstrap
   terraform init
   terraform apply -var aws_region=us-east-1   # creates datapond-terraform-state-<account-id>
   STATE_BUCKET=$(terraform output -raw state_bucket_name)
   cd ..
   ```

---

## 2. Apply infra

Do this **before** building images: the ECR repos that CI pushes to (step 3) are created
here, and they are `IMMUTABLE` — a push to a non-existent repo fails with "repository does
not exist". Apply first, then push.

```bash
cd terraform
terraform init \
  -backend-config="bucket=datapond-terraform-state-<ACCOUNT_ID>" \
  -backend-config="region=us-east-1"
terraform validate

terraform plan \
  -var domain=datapond.example.com \
  -var route53_zone_id=Z0123456789ABCDEF \
  -var acme_email=ops@example.com \
  -var 'db_subnet_ids=["subnet-0aaa1111","subnet-0bbb2222"]' \
  -var db_master_password='<strong-random-password>'

terraform apply \
  -var domain=datapond.example.com \
  -var route53_zone_id=Z0123456789ABCDEF \
  -var acme_email=ops@example.com \
  -var 'db_subnet_ids=["subnet-0aaa1111","subnet-0bbb2222"]' \
  -var db_master_password='<strong-random-password>'
```

Only these five vars are **required** — everything else has a workable default:

| Var | Required | Why |
|---|---|---|
| `domain` | yes | App hostname (Route53 A record + cert-manager cert + ingress). |
| `route53_zone_id` | yes | Hosted zone for the A record + DNS-01 solver. |
| `acme_email` | yes | Let's Encrypt account contact (cert-manager `ClusterIssuer`). |
| `db_subnet_ids` | yes | Aurora needs a DB subnet group spanning **≥ 2 AZs**. Pick two-plus subnet IDs from your VPC in different Availability Zones — `aws ec2 describe-subnets --filters Name=vpc-id,Values=<vpc-id> --query 'Subnets[].[SubnetId,AvailabilityZone]'` to list candidates. This has no default; `terraform plan` fails without it. |
| `db_master_password` | yes | Aurora master password (sensitive; no default). |

`vpc_id` / `subnet_id` are **optional** — omitted, they resolve to the account's default
VPC (`data.aws_vpc.selected` in `ec2.tf`), and the EC2 node's own security group is wired
automatically as Aurora's DB-ingress source (the T2 integration fix — no separate
`app_security_group_id` variable exists or is needed). `instance_type` defaults to
`m6i.xlarge` (4 vCPU/16 GB); `allowed_cidrs` defaults to `["0.0.0.0/0"]` for port 80/443
ingress — pass a customer CIDR allowlist here if the deployment shouldn't be open to the
internet. `app_version` defaults to `2.3.0` (must match whatever tag CI pushes in step 3 —
it seeds the node's cloud-init with the image tag used for `ecr-refresh`/pull auth, and
should match the Helm image tag the chart uses at install in step 5, though the chart
itself already defaults the image tag to `appVersion`).

This creates: two ECR repos (`datapond-backend`, `datapond-frontend`), the Aurora
Serverless v2 pgvector cluster, the S3 data bucket, IAM (node instance role: S3 + Bedrock +
ECR-pull + Route53 DNS-01/records + SSM), the EC2 node (Ubuntu 24.04, K3s via cloud-init) +
Elastic IP, the Route53 A record, the security group (443/80 in, **22 closed** — admin is
SSM-only), and the empty Secrets Manager DR vault (`datapond/critical-secrets`).

Cloud-init (`terraform/templates/user-data.sh.tftpl`) already, by the time `terraform
apply` returns and the instance finishes booting (check `/opt/datapond-ready` via SSM,
below):
- installs K3s (single-node) + Helm,
- installs cert-manager and a `letsencrypt-prod` `ClusterIssuer` (Route53 DNS-01),
- seeds and starts a systemd timer (`ecr-refresh.timer`, every 10h) that refreshes the
  `regcred` image-pull Secret from the node's own instance-profile credentials (ECR auth
  tokens expire every 12h; there's no static ECR credential anywhere).

It does **not** install the DataPond app — that's a deliberate manual gate so the
operator controls secret handling (step 4) and passes the DB password + deploy-time
outputs at install (step 5) rather than the node guessing them.

```bash
# Confirm cloud-init finished before continuing:
aws ssm start-session --target $(terraform output -raw node_instance_id)
# on the node:
cat /opt/datapond-ready   # expect: datapond-bootstrap-complete
tail -100 /var/log/datapond-bootstrap.log   # if it's not there yet
```

---

## 3. Build images

The ECR repos now exist (created by step 2). Images are built and pushed by CI, not on
the node (that was the bring-up hack this spec replaces). `.github/workflows/ecr-push.yml`
triggers on:

- **A published GitHub Release** (recommended for production cuts) — tags the images
  with the chart's `appVersion` (`helm/datapond/Chart.yaml`, currently `2.3.0`) unless
  overridden.
- **`workflow_dispatch`** with an explicit `tag` input — useful for a hotfix build
  without cutting a full release.

```bash
# Option A: cut a release (GitHub UI, or gh CLI)
gh release create v2.3.0 --title "v2.3.0" --notes "Single-node prod deploy"

# Option B: manual dispatch with an explicit tag
gh workflow run ecr-push.yml -f tag=2.3.0-hotfix1
```

The workflow builds `backend/Dockerfile --target enterprise` from the **repo root**
context (the P0-3/P0-4 requirement — the enterprise build needs `ee/` alongside
`backend/`) and `frontend/Dockerfile` from `frontend/`, then pushes both to
`datapond-backend:<tag>` / `datapond-frontend:<tag>` in the ECR repos created in step 2.

> **ECR repos are `IMMUTABLE`** (`terraform/ecr.tf`): pushing the same tag twice fails.
> Bump `appVersion` (or pass a distinct `-f tag=`) for every re-push, including hotfixes.

---

## 4. Seed the critical-secrets vault

`ENCRYPTION_KEY` (plus `JWT_SECRET`/`INTERNAL_API_KEY`) live only in the in-cluster
`datapond-secrets` Kubernetes Secret — they are **not durable across node loss**. If the
node is ever rebuilt and Helm regenerates a fresh `ENCRYPTION_KEY`, every credential
already encrypted-at-rest in Aurora under the old key becomes **permanently
undecryptable**. So the vault (`datapond/critical-secrets`, created empty by step 2) must
hold a copy of these values. The mechanics differ between a first install and a rebuild —
**pick the section that matches your situation.**

### 4a. Fresh install (primary path): let Helm generate, then mirror

On a brand-new cluster, **do NOT hand-create `datapond-secrets` before Helm** — a
`kubectl create secret` you make yourself lacks the Helm ownership metadata
(`app.kubernetes.io/managed-by`, release annotations), and the `helm upgrade --install` in
step 5 then aborts with *"Secret datapond-secrets ... cannot be imported into the current
release: invalid ownership metadata"*. Instead let Helm generate all of `ENCRYPTION_KEY`/
`JWT_SECRET`/`INTERNAL_API_KEY`/`ADMIN_PASSWORD` on first install (it does this
automatically — see `helm/datapond/templates/secrets.yaml`), then **immediately after step
5 completes and before any real connector credentials get stored**, mirror the DR subset
into the Secrets Manager vault:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
SM=datapond/critical-secrets   # deterministic name; works even without TF state
payload=$(kubectl -n datapond get secret datapond-secrets -o json | jq '{
  ENCRYPTION_KEY:   (.data.ENCRYPTION_KEY   | @base64d),
  JWT_SECRET:       (.data.JWT_SECRET       | @base64d),
  INTERNAL_API_KEY: (.data.INTERNAL_API_KEY | @base64d)
}')
aws secretsmanager put-secret-value --secret-id "$SM" --secret-string "$payload"
```

This is exactly the "One-time: seed the Secrets Manager vault" procedure in
[`docs/DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md) (§26). It is safe **as long as the
vault is seeded before the first time credentials get encrypted under this cluster's
`ENCRYPTION_KEY`** — right after install, nothing is encrypted yet.

Because 4a mirrors *after* step 5, on a fresh install **run step 5 next, then come back and
run the mirror command above.** Then retrieve and record the generated admin password:

```bash
kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d; echo
```

**Record the vault name (`datapond/critical-secrets`) and `ADMIN_PASSWORD` out-of-band**
(password manager) — in a real DR you may not have Terraform state handy to look up the
ARN via `terraform output -raw critical_secrets_arn`.

### 4b. Rebuild / restore: re-seed the Secret from the vault BEFORE the app

On a **node rebuild** (the Secrets Manager vault already holds the real values from a prior
install's 4a), you MUST restore `datapond-secrets` from the vault **before** `helm upgrade
--install`, so Helm's lookup-preserve logic adopts the restored key instead of generating a
fresh one that can't decrypt the restored Aurora's rows. This is the load-bearing
secrets-first ordering — the full procedure and its rationale are in
[`docs/DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md) (procedure B + "Restore ordering"):

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl create namespace datapond --dry-run=client -o yaml | kubectl apply -f -
SM=datapond/critical-secrets
vals=$(aws secretsmanager get-secret-value --secret-id "$SM" --query SecretString --output text)
kubectl -n datapond create secret generic datapond-secrets \
  --from-literal=ENCRYPTION_KEY="$(echo "$vals" | jq -r .ENCRYPTION_KEY)" \
  --from-literal=JWT_SECRET="$(echo "$vals" | jq -r .JWT_SECRET)" \
  --from-literal=INTERNAL_API_KEY="$(echo "$vals" | jq -r .INTERNAL_API_KEY)" \
  --dry-run=client -o yaml | kubectl apply -f -
# THEN run step 5 — the chart's lookup-preserve keeps these exact values.
```

(On this restore path Helm adopts a Secret it created originally, and lookup-preserve
reads the restored keys — no ownership-metadata conflict, unlike a hand-created Secret on a
truly fresh cluster.)

---

## 5. Install the app

Still on the SSM session on the node (cloud-init already installed K3s + Helm + cert-
manager). On a **fresh install** Helm generates `datapond-secrets` here (then do the 4a
mirror right after); on a **rebuild** step 4b already restored it from the vault.

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
cd /path/to/datapond   # a checkout of this repo on the node, or scp'd helm/ chart dir

DOMAIN=datapond.example.com
DB_MASTER_PASSWORD='<the same value you passed to terraform apply -var db_master_password>'

helm upgrade --install datapond helm/datapond -n datapond \
  --values helm/datapond/values-prod-single.yaml \
  --set externalDatabase.host=$(terraform -chdir=/path/to/terraform output -raw aurora_endpoint) \
  --set backend.image.repository=$(terraform -chdir=/path/to/terraform output -raw ecr_backend_repo_url) \
  --set frontend.image.repository=$(terraform -chdir=/path/to/terraform output -raw ecr_frontend_repo_url) \
  --set ingress.domain=$DOMAIN \
  --set postgres.auth.password="$DB_MASTER_PASSWORD"
```

`postgres.auth.password` MUST equal the Aurora master password you passed to `terraform
apply -var db_master_password` — the backend reads it from `datapond-secrets` (as
`POSTGRES_PASSWORD`) to build `DATABASE_URL`. Omit it and the chart falls through to a
freshly-random password that Aurora will reject, and the backend never comes up (this is
the exact failure the live bring-up hit).

If you don't have Terraform state locally on the node, get the three outputs from
wherever you ran `terraform apply` (step 2) and substitute them literally instead of
`terraform output`:

```bash
helm upgrade --install datapond helm/datapond -n datapond \
  --values helm/datapond/values-prod-single.yaml \
  --set externalDatabase.host=datapond-pg.cluster-xxxxx.us-east-1.rds.amazonaws.com \
  --set backend.image.repository=<acct>.dkr.ecr.us-east-1.amazonaws.com/datapond-backend \
  --set frontend.image.repository=<acct>.dkr.ecr.us-east-1.amazonaws.com/datapond-frontend \
  --set ingress.domain=datapond.example.com \
  --set postgres.auth.password='<the-aurora-master-password>'
```

`values-prod-single.yaml` already sets: `imagePullSecrets: [regcred]` (the Secret cloud-
init's `ecr-refresh` timer keeps current), `storage.provider=s3` with no static keys (node
instance-profile IAM), `externalDatabase.enabled=true` / `postgres.enabled=false`
(external Aurora, no in-cluster Postgres), the `foundation` workload set (backend/
frontend/valkey/litellm; Trino/Spark/Polaris/Airflow/MLflow/Jupyter/RisingWave/
OpenMetadata/Ollama/vLLM/MinIO all `enabled: false`), litellm's Bedrock model list
(Titan embed + Claude Haiku/Sonnet, `us-east-1`), and `ingress.tls.enabled=true` with the
`cert-manager.io/cluster-issuer: letsencrypt-prod` annotation. The image `tag` is not set
explicitly — it defaults to the chart `appVersion`, which must match whatever CI pushed
in step 3.

```bash
kubectl -n datapond rollout status deploy/backend
kubectl -n datapond rollout status deploy/frontend
```

---

## 6. Verify

```bash
# Frontend loads
curl -sk -o /dev/null -w '%{http_code}\n' https://datapond.example.com/        # expect 200

# Backend health
curl -sk -o /dev/null -w '%{http_code}\n' https://datapond.example.com/api/health   # expect 200

# Login issues a JWT (ADMIN_PASSWORD from step 4, or fetch it if auto-generated:
#   kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d)
curl -sk -X POST https://datapond.example.com/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<ADMIN_PASSWORD>"}' | jq .
# expect: HTTP 200 with a non-empty "access_token"

# cert-manager issued a real, Ready certificate (not the K3s self-signed default)
kubectl -n datapond get certificate
# expect: datapond-tls  READY=True

# litellm -> Bedrock: an AI SQL / RAG call should succeed with has_ai=true and no
# egress-policy 403 or Bedrock AccessDenied in backend logs
TOKEN=$(curl -sk -X POST https://datapond.example.com/api/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"admin","password":"<ADMIN_PASSWORD>"}' | jq -r .access_token)
curl -sk -X POST https://datapond.example.com/api/ai/sql -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"question":"show me 5 rows from any table"}' | jq .
kubectl -n datapond logs deploy/backend | grep -iE 'bedrock|litellm' | tail -20
```

Because this is a real Route53 domain over real HTTPS (not the `nip.io`/HTTP the bring-up
used), **WebAuthn/passkey login now works** — browsers require a genuine TLS origin for
passkeys; the earlier bring-up couldn't demo this.

All green here means: DNS resolves, TLS terminates with a trusted cert, the backend can
reach Aurora and decrypt/verify auth, and litellm can reach Bedrock through the node's
IAM role.

---

## 7. Disaster recovery

This deployment's availability posture is **"no HA, fast restore"** — a deliberate
single-node cost trade (design doc §1/§2), not an oversight. The full procedure —
Aurora PITR/snapshot restore, S3 object recovery, the Secrets-Manager-first restore
ordering, and the quarterly backup-verification drill — lives in
**[`docs/DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md)**. The one rule that matters enough
to repeat here: **on any rebuild, re-seed `datapond-secrets` from the
`datapond/critical-secrets` Secrets Manager vault BEFORE the backend is allowed to
connect to Aurora.** If Helm is allowed to regenerate `ENCRYPTION_KEY` first, every
encrypted credential already stored in Aurora becomes permanently unreadable. Expected
RTO: ~30-60 min for an Aurora-only restore, ~2-4 h for a full node rebuild (Terraform
apply + cloud-init + secrets re-seed + Helm install), per the DR doc's objectives table.

---

## 8. Teardown

Aurora has `deletion_protection=true` by default (P0-5) — it blocks a bare
`terraform destroy`. Flip it off first, then destroy:

```bash
cd terraform

terraform apply -var db_deletion_protection=false \
  -var domain=datapond.example.com \
  -var route53_zone_id=Z0123456789ABCDEF \
  -var acme_email=ops@example.com \
  -var 'db_subnet_ids=["subnet-0aaa1111","subnet-0bbb2222"]' \
  -var db_master_password='<strong-random-password>'

# If the S3 data bucket is non-empty and versioned, `terraform destroy` will fail on it
# (S3 buckets with objects/versions can't be deleted directly) — empty it first:
BUCKET=$(terraform output -raw bucket_name)
aws s3api list-object-versions --bucket "$BUCKET" \
  --query '{Objects: [Versions,DeleteMarkers][].{Key:Key,VersionId:VersionId}}' \
  --output json > /tmp/versions.json
# delete every version + delete-marker (script this for buckets with many objects), e.g.:
aws s3api delete-objects --bucket "$BUCKET" --delete file:///tmp/versions.json

terraform destroy \
  -var domain=datapond.example.com \
  -var route53_zone_id=Z0123456789ABCDEF \
  -var acme_email=ops@example.com \
  -var 'db_subnet_ids=["subnet-0aaa1111","subnet-0bbb2222"]' \
  -var db_master_password='<strong-random-password>'
```

A second destroy attempt in the same account will also collide on the fixed
`final_snapshot_identifier` (`datapond-pg-final-snapshot`) left by the previous destroy —
delete that RDS snapshot first, or pass `-var db_skip_final_snapshot=true` for a
disposable/test environment where the final snapshot isn't needed. Everything else
(ECR repos, EC2/EIP, IAM role, Route53 A record, Secrets Manager vault) is destroyed
in-band by `terraform destroy` — there is nothing left to clean up out-of-band.
