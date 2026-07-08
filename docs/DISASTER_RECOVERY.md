# DataPond Disaster Recovery Runbook

Covers the AWS-native profile (Aurora pgvector + native S3). Non-AWS profiles use
in-cluster MinIO/Postgres and are out of scope here.

## Objectives

| Metric | Target |
|---|---|
| RPO (data loss window) | ≤ 5 min for Aurora (continuous backup); PITR horizon = 14 days (`db_backup_retention_period`) |
| RTO (Aurora restore) | ~30–60 min (PITR/snapshot restore to a new cluster) |
| RTO (full cluster rebuild) | ~2–4 h (Terraform apply + Helm install + secret re-seed) |

## What holds what
- **Aurora pgvector** — app DB **and** RAG vectors (`ai_collections`/`ai_chunks`) **and**
  encrypted stored credentials (connector secrets, provider keys). Aurora backup = data + vectors.
- **S3 (`datapond-iceberg`)** — Iceberg tables + RAG source docs. Versioned; noncurrent versions culled after 90d.
- **`datapond-secrets` (K8s)** — `ENCRYPTION_KEY`, `JWT_SECRET`, `INTERNAL_API_KEY`, `ADMIN_PASSWORD`. Helm-generated, preserved across upgrades via in-cluster lookup. **Not durable across a cluster loss** → mirrored to Secrets Manager (below).

## ⚠️ Restore ordering (critical)
`ENCRYPTION_KEY` decrypts credentials STORED IN Aurora. If the cluster is lost and
Helm regenerates a fresh key, a restored Aurora's encrypted rows become permanently
undecryptable. **Always re-seed `datapond-secrets` from Secrets Manager BEFORE the
backend connects to the restored Aurora.** (Extends the P0-1a preflight in AWS_MVP_RUNBOOK §7.)

## One-time: seed the Secrets Manager vault (after first install)
```bash
SM=datapond/critical-secrets   # deterministic name — works even if terraform state is unavailable
# convenience alternative (needs TF state): SM=$(terraform -chdir=terraform output -raw critical_secrets_arn)
ns=datapond
payload=$(kubectl -n $ns get secret datapond-secrets -o json | jq '{
  ENCRYPTION_KEY:   (.data.ENCRYPTION_KEY   | @base64d),
  JWT_SECRET:       (.data.JWT_SECRET       | @base64d),
  INTERNAL_API_KEY: (.data.INTERNAL_API_KEY | @base64d)
}')
aws secretsmanager put-secret-value --secret-id "$SM" --secret-string "$payload"
```
Re-run whenever these values legitimately change (they normally never do).
**Record the vault name/ARN (`datapond/critical-secrets`) out-of-band** (password manager,
runbook) — in a real DR you may not have terraform state to look it up.

## Recovery procedures

### A. Aurora — point-in-time / snapshot restore
> **Networking (critical):** the restore commands MUST pass the stack's subnet group
> (`datapond-aurora`) and SG (`datapond-aurora-sg`) — otherwise the restored cluster
> lands in the default VPC/SG and the app cannot reach it. A restored cluster also has
> NO instances; you must add a `db.serverless` instance before it accepts connections.
```bash
SUBNET_GROUP=datapond-aurora
SG_ID=$(aws ec2 describe-security-groups \
  --filters Name=group-name,Values=datapond-aurora-sg \
  --query 'SecurityGroups[0].GroupId' --output text)

# Find an available snapshot id (automatic or the final snapshot):
aws rds describe-db-cluster-snapshots --db-cluster-identifier datapond-pg \
  --query 'DBClusterSnapshots[].DBClusterSnapshotIdentifier'

# PITR to a new cluster (within the 14-day window):
aws rds restore-db-cluster-to-point-in-time \
  --source-db-cluster-identifier datapond-pg \
  --db-cluster-identifier datapond-pg-restored \
  --restore-to-time <UTC-timestamp> \
  --db-subnet-group-name "$SUBNET_GROUP" --vpc-security-group-ids "$SG_ID"
# or from the automatic/final snapshot:
aws rds restore-db-cluster-from-snapshot \
  --db-cluster-identifier datapond-pg-restored \
  --snapshot-identifier <snapshot-id> --engine aurora-postgresql \
  --db-subnet-group-name "$SUBNET_GROUP" --vpc-security-group-ids "$SG_ID"

# The restored cluster has NO instances — add a serverless writer (matches
# aws_rds_cluster_instance in aurora.tf) before it accepts connections:
aws rds create-db-instance \
  --db-instance-identifier datapond-pg-restored-1 \
  --db-instance-class db.serverless \
  --engine aurora-postgresql \
  --db-cluster-identifier datapond-pg-restored
# (cluster-level serverlessv2_scaling_configuration governs scaling:
#  MinCapacity=0.5, MaxCapacity=4.0 — no per-instance scaling flag needed)

# then point Helm externalDatabase.host at the new writer endpoint.
```

#### A.1 Reconcile with Terraform state (do this BEFORE any `terraform apply`)
TF state manages `aws_rds_cluster.aurora` = `datapond-pg`. Restoring to a different id
(`datapond-pg-restored`) leaves state pointing at a cluster that no longer exists — a bare
`terraform apply` would then try to **recreate an empty `datapond-pg`**. Pick ONE:
- **(preferred) restore into the ORIGINAL identifier `datapond-pg`** — once the old cluster
  is fully gone, use `--db-cluster-identifier datapond-pg` (and instance `datapond-pg-1`) in
  the commands above. It stays under TF management; no import needed.
- **restore to a new id, then import** — `terraform import aws_rds_cluster.aurora datapond-pg-restored`
  and `terraform import aws_rds_cluster_instance.aurora datapond-pg-restored-1`, updating any
  hardcoded identifier in the config to match.

**Do NOT run `terraform apply` until the restored cluster is reconciled with state.**

### B. Secrets — re-seed BEFORE app start
```bash
SM=datapond/critical-secrets   # deterministic — no TF state needed
# convenience alternative: SM=$(terraform -chdir=terraform output -raw critical_secrets_arn)
vals=$(aws secretsmanager get-secret-value --secret-id "$SM" --query SecretString --output text)
kubectl -n datapond create secret generic datapond-secrets \
  --from-literal=ENCRYPTION_KEY="$(echo "$vals" | jq -r .ENCRYPTION_KEY)" \
  --from-literal=JWT_SECRET="$(echo "$vals" | jq -r .JWT_SECRET)" \
  --from-literal=INTERNAL_API_KEY="$(echo "$vals" | jq -r .INTERNAL_API_KEY)" \
  --dry-run=client -o yaml | kubectl apply -f -
# THEN helm upgrade — lookup-preserve keeps these exact values.
```

### C. S3 — recover a deleted/overwritten object
```bash
aws s3api list-object-versions --bucket datapond-iceberg --prefix <key>
# remove a delete-marker to restore, or copy a prior version id back over the key.
```

### D. Full cluster rebuild (order)
1. Reconcile the restored Aurora with TF state (§A.1) FIRST, then `terraform apply`
   (Aurora + S3 already exist / restored per A & C). A bare apply against a mismatched
   state recreates an empty `datapond-pg` — see §A.1.
2. Re-seed `datapond-secrets` from Secrets Manager (procedure B).
3. `helm upgrade --install` with `externalDatabase.host` = restored Aurora writer.
4. Verify (drill below).

## Quarterly backup-verification drill
1. Find a snapshot id
   (`aws rds describe-db-cluster-snapshots --db-cluster-identifier datapond-pg --query 'DBClusterSnapshots[].DBClusterSnapshotIdentifier'`)
   and restore the latest Aurora snapshot to a scratch cluster (procedure A — remember the
   subnet group / SG flags and the `create-db-instance` step).
2. `psql` → `SELECT count(*) FROM ai_chunks;` — vectors present.
3. Re-seed secrets from SM into a scratch namespace; confirm the backend can decrypt
   a stored connector credential (Settings → connector → test) — proves ENCRYPTION_KEY match.
4. Tear down the scratch cluster. Record the drill date + RTO observed.
