# DataPond AWS Production Deployment — Single-Node K3s (Design)

**Date**: 2026-07-10
**Status**: Design approved (pre-plan)
**Supersedes (deployment decision only)**: the EKS deployment line in `docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md` §3/§5. The pivot spec's positioning, 2-tier vector store, and AWS-managed analytics hybrid still stand; this spec fixes the *deployment topology* to what was validated + hardened.

**Context**: A live AWS bring-up (2026-07-09, torn down) validated the DataPond `foundation` profile end-to-end on a single-node K3s EC2 box against external Aurora Serverless v2 + S3 + Bedrock (login E2E, pgvector, IAM-based S3, litellm→Bedrock all working). It surfaced 8 fresh-install bugs, all now fixed on `main` (#114–#117). This spec turns that validated topology into a **production, customer-facing** deployment, operationalizing the three things the demo left as hacks: images built on-node → **ECR**, ephemeral public IP → **Elastic IP**, nip.io/HTTP → **real Route53 domain + Let's Encrypt TLS**.

## 1. Decisions (confirmed)

| Axis | Decision | Rationale |
|---|---|---|
| Purpose | Production / customer-facing | Highest rigor: TLS, backups/DR, stable address, repeatable IaC |
| Compute | **Single-node K3s on EC2** (NOT EKS) | Cost/simplicity over HA; availability = P0-5 backups + fast-restore. Node auth via `iam.tf` instance profile (IRSA stays EKS-dormant) |
| Availability | No HA by choice; RTO ~2–4 h via P0-5 restore | Node loss → `terraform apply` replacement + re-seed secrets; Aurora/S3 are external and survive |
| Images | **ECR + CI build/push** | Replaces the ~9-min on-node build/tar-sync; production-repeatable, versioned |
| TLS/domain | **Route53 domain + cert-manager (Let's Encrypt DNS-01)** + Traefik | Free auto-renewing certs, simplest on single-node K3s; DNS-01 needs Route53 perms (already needed for the A record) |
| Address | **Elastic IP** + Route53 A record | Stable hostname across restarts |
| Components | **foundation profile** (backend/frontend/valkey/litellm) + external Aurora/S3/Bedrock | Only sane scope for one node; spec-aligned. Heavy analytics = AWS-managed (Athena/EMR Serverless) |
| Instance | **m6i.xlarge** (4 vCPU/16 GB), 60 GB gp3 root | Headroom over the t3.xlarge that ran foundation; tunable |
| Region | us-east-1 (var) | Bedrock model + Aurora availability; parameterized |

## 2. Compute & availability

One `aws_instance` (m6i.xlarge, 60 GB gp3, `delete_on_termination`) in a **public subnet**, with an **`aws_eip`** associated. K3s single-node (`--write-kubeconfig-mode 644`). The node's **instance profile** (`iam.tf` `datapond-app-role`) is the sole AWS identity — S3, Bedrock, and (new) ECR-pull + Route53-DNS-01. Admin access is **SSM only** (SSM agent + `AmazonSSMManagedInstanceCore` on the role, baked into `iam.tf` this time, not out-of-band); **port 22 closed**.

**Availability**: single-node, no HA — an explicit cost trade. The recovery story is the P0-5 DR runbook: Aurora (PITR/snapshots) and S3 (versioned) are external and survive node loss; a replacement node is `terraform apply` + cloud-init + Helm-install-from-ECR + **re-seed `datapond-secrets` from the Secrets Manager vault BEFORE the app connects to Aurora** (else stored encrypted creds are undecryptable). Documented RTO ~2–4 h.

## 3. Image delivery — ECR + CI

- Terraform creates **ECR repos** `datapond-backend`, `datapond-frontend` (+ optional `datapond-jupyter`), with lifecycle policy (keep last N tags).
- **GitHub Actions** release job: `docker build -f backend/Dockerfile --target enterprise .` (repo-root context — the P0-3/P0-4 requirement) + `frontend/`, tag `:<chart appVersion>` + `:<git sha>`, `aws ecr get-login-password | docker login`, push. Runs on tag/release (not every commit).
- **Node pulls from ECR**: instance profile gains `ecr:GetAuthorizationToken` (resource `*`) + `ecr:BatchGetImage`/`GetDownloadUrlForLayer`/`BatchCheckLayerAvailability` (scoped to the two repo ARNs). ECR auth tokens expire every 12 h, and K3s `registries.yaml` only takes static credentials — so the reliable path is a **systemd timer (~10 h) that runs `aws ecr get-login-password` and patches the namespace `regcred` dockerconfig Secret** (referenced via `imagePullSecrets`). Cloud-init seeds it once at boot; the timer keeps it fresh. (The instance profile supplies the AWS creds — no static keys.)
- Helm: `backend.image.repository` / `frontend.image.repository` set to the ECR URIs (values-prod-single or `--set` at install); `tag` = chart appVersion (P0-4 pinning preserved). `imagePullPolicy: IfNotPresent`.

## 4. Networking, TLS, domain

- **VPC**: use the account default VPC + a public subnet (bring-up validated), or a dedicated `/24` (var-toggle; default = existing VPC to keep it simple). Node gets the EIP.
- **Route53**: a hosted zone for `<yourdomain>` (existing or Terraform-created); an **A record** `datapond.<yourdomain>` → the EIP.
- **TLS**: **cert-manager** on K3s issues a Let's Encrypt cert via **DNS-01** (Route53 solver; the instance profile grants `route53:GetChange` + `route53:ChangeResourceRecordSets` on the zone). Traefik ingress uses the cert; `ingress.domain = datapond.<yourdomain>`, `ingress.tls.enabled = true`.
- **SG**: inbound **443** from `0.0.0.0/0` (or a customer CIDR allowlist var), **80** → Traefik 301→443, **22 CLOSED**. Egress all (ECR/Bedrock/Aurora/ACME/Route53).
- Ingress paths render per enabled service (foundation → `/` frontend, `/api` backend) — the path-gating already in the chart.

## 5. Data & AI layer

- **Aurora Serverless v2 PostgreSQL** (engine `var.db_engine_version` default 15.10 — the #115 fix; 0.5–4 ACU, external, multi-AZ subnet group), **pgvector** (`CREATE EXTENSION` on first bootstrap). Deletion protection ON, 14-day PITR.
- **S3** data bucket (account-scoped name per #114, versioned + SSE + lifecycle), IAM-role access (no static keys — `storage.endpoint=""`).
- **Bedrock** via the instance profile (litellm foundation config: Titan embed + Claude Haiku/Sonnet, us-east-1; validated live). Account must have **Bedrock model access enabled** for those models (console/API, one-time).
- Analytics (**Athena / EMR Serverless**) AWS-managed per the pivot spec — not on the node; out of scope for the node deployment.

## 6. Backups / DR (P0-5, already merged)

Aurora 14-day PITR + deletion protection + final snapshot; S3 versioning + noncurrent-version lifecycle; remote Terraform state (account-scoped bucket, partial backend); Secrets Manager `critical-secrets` vault seeded from the running `datapond-secrets` (DR §26 mirror). `docs/DISASTER_RECOVERY.md` is the single-node availability contract. **Secrets-first restore ordering is load-bearing.**

## 7. Deploy automation

Terraform (`terraform/`) provisions: EIP, EC2 (m6i.xlarge) + instance profile (S3+Bedrock+ECR+Route53+SSM), Aurora, S3, ECR repos, Secrets Manager vault, Route53 A record, SG. Cloud-init/user-data installs K3s + Helm + cert-manager, then Helm-installs the `foundation` profile from ECR with `externalDatabase.host = <aurora endpoint>`, `ingress.domain`, and secrets injected (`ADMIN_PASSWORD`/`ENCRYPTION_KEY`/`JWT_SECRET`/etc. from a provisioning step or the vault). A `values-prod-single.yaml` profile captures the single-node production values (foundation + ECR images + ingress/TLS + externalDatabase).

**All 8 bring-up bugs are already fixed on `main`** (#114 state bucket, #115 engine version, #116 ×4 connectivity+airflow-PVC, #117 auth ×2), so a fresh install from `main` is clean. New work this spec introduces (not yet built): ECR repos + CI push + node pull auth; Elastic IP; cert-manager + Route53 DNS-01 + real-domain ingress; the SSM policy folded into `iam.tf`; a `values-prod-single.yaml`; the m6i.xlarge EC2 + cloud-init in Terraform (the bring-up did the EC2 by hand).

## 8. Out of scope (YAGNI)

EKS / multi-node HA (explicit cost trade — revisit if the customer needs an SLA); the IRSA roles (#112/#103 — EKS-only, stay dormant); OpenSearch Serverless (spec's tier-2 vector extension, defer to when pgvector is outgrown); in-cluster Trino/Spark/Polaris/Airflow/OpenMetadata (AWS-managed instead); multi-region; ALB/ACM (using Traefik+cert-manager instead); the streaming (RisingWave) path (disabled on foundation; its cred-chain fix #113 stands for when re-enabled).

## 9. Open items for deploy-time (not blockers)

- The customer's **domain** + Route53 hosted zone (parameterized `var.domain`, `var.route53_zone_id`).
- **Bedrock model access** enablement in the target account (one-time console/API).
- SG inbound scope: open `443` to the internet vs a **customer CIDR allowlist** (`var.allowed_cidrs`, default `0.0.0.0/0`).
- Instance size final call (m6i.xlarge default; bump if the customer's load profile is known).
