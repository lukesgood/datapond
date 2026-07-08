# Backup & Disaster Recovery (P0-5) — Design

**Date**: 2026-07-08
**Status**: Design approved (pre-implementation)
**Context**: The AWS reference Terraform (8 hand-written .tf files) has CRITICAL backup/DR gaps: Aurora `skip_final_snapshot=true` + default 1-day retention + no deletion protection; Terraform state is LOCAL (no backend — losing operator disk orphans infra, state holds plaintext DB password); critical secrets (esp. `ENCRYPTION_KEY`) live ONLY in the K8s `datapond-secrets` (cluster loss → Aurora's encrypted credentials become permanently undecryptable even after snapshot restore). Vectors live in Aurora pgvector, so Aurora's backup posture fully determines RAG-data RPO/RTO. No DR runbook, no RPO/RTO, no restore drill exist.

## 1. Decisions (confirmed)

| Decision | Choice |
|---|---|
| Scope | **Core single-region data-durability + DR runbook.** Aurora backup hardening, S3 SSE+lifecycle, remote TF state, secrets durability, DR runbook. DEFER multi-region (CRR, cross-region snapshot copy, HA reader, Object Lock) |
| Secrets DR | **Documented backup/restore to AWS Secrets Manager.** Helm stays the runtime generator (P0-1a unchanged); TF creates an empty SM vault; documented seed (post-install) + restore (pre-rebuild) procedures |
| Parameterization | **Terraform variables with DR-safe defaults** (Approach A) — prod-safe by default, dev-overridable; matches the hand-written 8-file stack style (no modules) |
| Verification | terraform fmt/validate in a new CI job (terraform not installed locally; no live apply — that's the separate AWS-live backlog item) |

## 2. Aurora backup hardening (`terraform/aurora.tf`, `variables.tf`)

New variables (DR-safe defaults) wired into `aws_rds_cluster.aurora`:

| Variable | Default | Purpose |
|---|---|---|
| `db_backup_retention_period` | `14` | PITR window (days) — defines RPO |
| `db_deletion_protection` | `true` | Block `terraform destroy`/console deletion |
| `db_skip_final_snapshot` | `false` | Take a final snapshot on destroy |
| `db_preferred_backup_window` | `"03:00-04:00"` | UTC backup window |
| `db_preferred_maintenance_window` | `"sun:04:30-sun:05:30"` | UTC maintenance window |
| `db_kms_key_id` | `null` | Optional CMK (null ⇒ AWS-managed `aws/rds`) |

Cluster resource changes:
- `skip_final_snapshot = var.db_skip_final_snapshot`
- `final_snapshot_identifier = "${var.cluster_identifier}-final-snapshot"` — a FIXED, deterministic name (NO `timestamp()`/`formatdate` — those cause a perpetual plan diff). Referenced only when skip is false. Documented caveat: a second destroy needs the prior final snapshot renamed/removed first (rare operator concern), acceptable vs. the perpetual-diff alternative.
- `backup_retention_period = var.db_backup_retention_period`, `preferred_backup_window`, `preferred_maintenance_window`, `deletion_protection = var.db_deletion_protection`, `copy_tags_to_snapshot = true`, `kms_key_id = var.db_kms_key_id`.
- `storage_encrypted = true` unchanged (already correct).

Accepted follow-up (documented, not silently dropped): single Aurora instance = no compute HA reader. Aurora storage is already 3-AZ replicated; a reader instance for AZ failover is part of the deferred multi-region/HA tier.

## 3. S3 durability (`terraform/s3.tf`, `variables.tf`)

- **`aws_s3_bucket_server_side_encryption_configuration`** on `aws_s3_bucket.data`: `sse_algorithm = "AES256"` (or `aws:kms` if a bucket CMK var is set later), `bucket_key_enabled = true`. Makes encryption explicit/enforced instead of relying on the account default.
- **`aws_s3_bucket_lifecycle_configuration`**: rule expiring **noncurrent** versions after `var.s3_noncurrent_version_expiration_days` (default `90`) + `abort_incomplete_multipart_upload` after 7 days. No expiration of current objects (lakehouse/Iceberg data is permanent).
- Versioning + public-access-block unchanged (already correct).
- Deferred to multi-region tier: CRR, Object Lock (WORM), access logging.

## 4. Remote Terraform state (`terraform/backend.tf`, `terraform/bootstrap/`, README)

- **`backend "s3"`** block: `bucket = <state bucket>`, `key = "datapond/terraform.tfstate"`, `region`, `encrypt = true`, `use_lockfile = true` (S3-native locking — no DynamoDB table needed on Terraform ≥1.10). The AWS provider `required_version` is bumped to `>= 1.10` if below.
- **Bootstrap** (`terraform/bootstrap/main.tf`): a tiny standalone config creating the versioned + encrypted + public-access-blocked state bucket, with local state (acceptable — it only creates one bucket). README documents: run bootstrap once → `terraform init -migrate-state` in the main config.
- Closes the "local state orphans infra + leaks DB password" gap. State bucket versioning gives state history/rollback.

## 5. Secrets durability (`terraform/secrets.tf`, runbook)

- **`aws_secretsmanager_secret` `datapond/critical-secrets`** created by TF — EMPTY (no `aws_secretsmanager_secret_version` with real values; values are Helm-generated at runtime and TF-managed values would leak into state). Attributes: `recovery_window_in_days = 30`, tags, optional `kms_key_id`.
- The DB master password: replace the apply-time `-var db_master_password` (state + shell-history exposure) with a TF-created SM secret the operator populates once; Aurora reads it via a documented data source or the operator supplies it. (Impl note: keep it simple — TF creates the SM secret; Aurora `master_password` still comes from `var.db_master_password` but the runbook directs storing/retrieving it via SM rather than raw `-var`; avoids a data-source cycle. The plan picks the exact wiring.)
- Runbook procedures (Section 6): post-install **seed** (push `ENCRYPTION_KEY`/`JWT_SECRET`/`INTERNAL_API_KEY` from `datapond-secrets` into SM) and DR **restore** (pull from SM → recreate `datapond-secrets` BEFORE `helm upgrade`, so lookup-preserve finds the original `ENCRYPTION_KEY`).

## 6. DR runbook (`docs/DISASTER_RECOVERY.md`)

New doc:
- **RPO/RTO targets**: RPO ≤ backup-window granularity (continuous backup → practically minutes; PITR horizon = retention 14 days); RTO stated per component (Aurora restore, cluster rebuild).
- **Component restore matrix**: Aurora (PITR restore + snapshot restore commands), S3 (noncurrent-version recovery, delete-marker removal), secrets (SM re-seed), full cluster rebuild.
- **Restore ORDERING (critical)**: re-seed `datapond-secrets` (esp. `ENCRYPTION_KEY`) from SM **before** the app connects to a restored Aurora — otherwise stored encrypted credentials are undecryptable. Cross-links the P0-1a preflight (AWS_MVP_RUNBOOK §7).
- **Backup-verification drill** (quarterly checklist): restore a snapshot to a scratch cluster, confirm pgvector `ai_chunks` rows present + a stored connector credential decrypts.

## 7. CI + testing

- New **`terraform-validate`** job in `.github/workflows/ci.yml` (or a new workflow): `hashicorp/setup-terraform`, then `terraform fmt -check -recursive terraform/`, `terraform init -backend=false` (both root + bootstrap), `terraform validate`. Authoritative syntax/wiring gate.
- No `plan`/`apply` (needs AWS creds — the separate AWS-live backlog item validates real backup behavior).
- Config-only + docs: no runtime/pytest surface.

## 8. Out of scope

Cross-region S3 replication (CRR); Aurora cross-region automated-backup replication / cross-region snapshot copy; HA reader instance (AZ compute failover); S3 Object Lock (WORM); CMK creation (variable hook added, key not provisioned); External Secrets Operator; actually running `terraform apply` (AWS-live backlog item); backup of in-cluster MinIO (non-AWS profiles — AWS profile uses native S3).
