# Operations Pause — Live Environment Stopped (Concept Re-confirmation)

> **State: PAUSED.** The live AWS operational environment was intentionally stopped to
> halt run cost while the product **concept is re-confirmed** before a restart. Nothing was
> destroyed — all data, images, catalog, secrets, and DNS are preserved and the system is
> restartable. See "Restart procedure" below.

## Why

Following the strategy + validation work in `docs/ONTOLOGY_FEASIBILITY_REPORT.md`, the decision
is to **pause operations and re-confirm the product concept** (positioning, target vertical,
product-only vs services, ontology scope) before continuing to invest. The binding constraint
identified is **demand**, not technology — so the live system is paused rather than extended.

## What was stopped (and what stays)

| Resource | Action | State after |
|---|---|---|
| EC2 node `i-0bbf886f0728f3e6e` (m6i.xlarge, **persistent spot, stop-behavior**) | `stop-instances` | stopped (restartable) |
| Aurora Serverless v2 cluster `datapond-pg` (aurora-postgresql, 0.5–4 ACU) | `stop-db-cluster` | stopped (data retained) |
| EventBridge Scheduler `datapond-node-start` / `datapond-node-stop` | set **DISABLED** | won't auto-restart the node |

**Preserved (untouched):** S3 bucket `datapond-iceberg` (all data + warehouse + athena results),
ECR images (`datapond-backend`, `datapond-frontend`; live tags backend `2.3.0-20aad91`,
frontend `2.3.0-84ca7ae`* build path), Glue/Athena catalog, Secrets Manager, Route53 domain
`datapond.csg.fitcloud.co.kr`, the Helm release manifest, and Aurora data (stopped, not deleted).

*Frontend was last deployed at `2.3.0-e3719b2`; `84ca7ae` is the latest committed frontend but
was a docs commit — confirm the running image tag on restart with the command below.

## Cost while paused

- **EC2 stopped** → no compute/spot charge; only the small EBS **root volume** is billed.
- **Aurora stopped** → no ACU compute; only **cluster storage** is billed.
- **S3 / ECR / snapshots** → storage only. **Route53** → hosted-zone fee.
- Net: near-minimal; the two compute cost drivers (EC2 + Aurora ACU) are off.

## ⚠ Important caveats

1. **Aurora auto-restarts after 7 days.** AWS force-starts a stopped DB cluster after 7 days.
   For a pause longer than a week, EITHER re-run `stop-db-cluster` weekly, OR (for a long/
   indefinite pause) **snapshot + delete** the cluster and restore later — a bigger, explicit
   decision, intentionally NOT taken here so the environment stays trivially restartable.
   Continuous/automated Aurora backups remain, so a restore point exists regardless.
2. **Schedulers are DISABLED.** They will NOT bring the node back. To resume automated
   weekday start/stop, re-enable them (see restart) — otherwise start the node manually.
3. **Spot capacity on restart** is not guaranteed instantly; the persistent spot request retries
   until capacity is available.

## Restart procedure

```bash
R="--region us-east-1"
# 1) Start the database first (wait until 'available' — a few minutes)
aws rds start-db-cluster --db-cluster-identifier datapond-pg $R
aws rds describe-db-clusters --db-cluster-identifier datapond-pg $R --query "DBClusters[].Status" --output text

# 2) Start the compute node (persistent spot resumes)
aws ec2 start-instances --instance-ids i-0bbf886f0728f3e6e $R
aws ec2 describe-instances --instance-ids i-0bbf886f0728f3e6e $R --query "Reservations[].Instances[].State.Name" --output text

# 3) (optional) re-enable the weekday start/stop automation
#    aws scheduler update-schedule --name datapond-node-start --state ENABLED ... (re-supply required fields)
#    aws scheduler update-schedule --name datapond-node-stop  --state ENABLED ...

# 4) Wait for k3s + pods to come up on the node, then verify
#    (SSM on the node — same channel used for deploys)
ID=$(aws ssm send-command --instance-ids i-0bbf886f0728f3e6e --document-name AWS-RunShellScript \
  --parameters 'commands=["kubectl -n datapond get pods -o wide"]' $R --query Command.CommandId --output text)
sleep 15; aws ssm get-command-invocation --command-id "$ID" --instance-id i-0bbf886f0728f3e6e $R --query StandardOutputContent --output text

# 5) Confirm running image tags + health
#    kubectl -n datapond get deploy backend frontend -o custom-columns=NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image
curl -s -o /dev/null -w '%{http_code}\n' https://datapond.csg.fitcloud.co.kr/api/health   # expect 200
```

Notes on restart:
- Backend must reach Aurora — **start Aurora before the node** (step 1 before 2) so pods find the DB.
- The live deploy mechanism is unchanged (laptop `git archive` → S3 → SSM build-on-node → ECR
  push via okr-deployer token → `helm upgrade --reset-then-reuse-values`; frontend-only path in
  scratchpad `redeploy-fe.sh`). See the deploy memory / prior runbook.
- If the node's k3s state didn't survive the stop cleanly, `helm -n datapond history datapond`
  and re-`helm upgrade` with the current image tags.

## Key identifiers

| | Value |
|---|---|
| Region | `us-east-1` · Account `588738574974` (IAM user `okr-deployer`) |
| EC2 node | `i-0bbf886f0728f3e6e` (m6i.xlarge, persistent spot) |
| Aurora | cluster `datapond-pg` (Serverless v2, 0.5–4 ACU) |
| Schedulers | `datapond-node-start`, `datapond-node-stop` (EventBridge Scheduler, DISABLED) |
| Bucket | `s3://datapond-iceberg` |
| Domain | `datapond.csg.fitcloud.co.kr` |
| Helm | release `datapond`, namespace `datapond` |

## Concept status (what "re-confirm" means)

Re-confirmation covers the open strategic questions surfaced this cycle:
- **Positioning** — lead with governance + portability (not "AI Data Foundation" breadth, not RAG).
- **Ontology scope** — validated as a *governance + relationship + jargon-vertical* play, **not**
  a general "better search" play (see `ONTOLOGY_FEASIBILITY_REPORT.md`; concept layer is
  self-serve-feasible, relations are the weak spot, retrieval lift is conditional).
- **Business model** — product-only pivot hinges on self-serve ontology (partially validated) +
  a hosted tier + a PLG-friendly segment; services (FDE) is a trap to avoid.
- **Next gate (before rebuild):** validate **demand** with a design partner in one jargon-heavy
  regulated vertical (medical coding / legal / finance) — do not build ahead of demand.

Restart is warranted once the concept + a design-partner demand signal are confirmed.
