# Operations — Live Environment Stop / Restart Runbook

> **State as of 2026-08-31: RUNNING on a weekday schedule.** The EventBridge schedulers
> are **ENABLED** again, so the node stops and starts on its own:
>
> | Schedule | Cron (Asia/Seoul) | Effect |
> |---|---|---|
> | `datapond-node-start` | `cron(30 7 ? * MON-FRI *)` | node up at 07:30 on weekdays |
> | `datapond-node-stop` | `cron(0 18 ? * MON-FRI *)` | node down at 18:00 on weekdays |
>
> The environment is therefore **down outside 07:30–18:00 KST on weekdays, and all
> weekend**. That is deliberate — it is a spot instance and evenings cost money for
> nothing — but it means a health check outside those hours is not evidence of a fault.
>
> The same schedule is declared to the application in `values-prod-single.yaml` as
> `backend.systemEvents.expectedStarts`, so Infrastructure → Events records the morning
> start as information rather than as a critical restart with no known cause. **If the
> schedule changes, change it in both places** — otherwise every scheduled start
> reappears as an incident, and the real ones stop standing out.
>
> **History.** The environment was intentionally stopped on 2026-07-27 to halt run cost
> while the product concept was re-confirmed (`CONCEPT_RECONFIRMATION.md`). Nothing was
> destroyed at any point — data, images, catalog, secrets, and DNS were preserved
> throughout.

## Cost note from the 2026-07 pause

Caveat 1 below was not acted on: the Aurora cluster was never re-stopped weekly, so AWS
force-started it roughly seven days into the pause and it billed ACU from then until the
2026-08-24 restart — about four weeks. Only the EC2 node stayed down for the full pause.
Any future pause longer than a week needs either a weekly re-stop or the snapshot+delete
path.

## Why the 2026-07 pause happened

Following the strategy + validation work in `docs/ONTOLOGY_FEASIBILITY_REPORT.md`, the decision
was to **pause operations and re-confirm the product concept** (positioning, target vertical,
product-only vs services, ontology scope) before continuing to invest. The binding constraint
identified was **demand**, not technology — so the live system was paused rather than extended.

## Stop procedure (what to stop, and what stays)

| Resource | Action | State after |
|---|---|---|
| EC2 node `i-0bbf886f0728f3e6e` (m6i.xlarge, **persistent spot, stop-behavior**) | `stop-instances` | stopped (restartable) |
| Aurora Serverless v2 cluster `datapond-pg` (aurora-postgresql, 0.5–4 ACU) | `stop-db-cluster` | stopped (data retained, **re-stop weekly** — caveat 1) |
| EventBridge Scheduler `datapond-node-start` / `datapond-node-stop` | set **DISABLED** | won't auto-restart the node |

Commands (region `us-east-1`):

```bash
R="--region us-east-1"
aws ec2 stop-instances --instance-ids i-0bbf886f0728f3e6e $R
aws rds stop-db-cluster --db-cluster-identifier datapond-pg $R
aws scheduler update-schedule --name datapond-node-start --state DISABLED ...  # re-supply required fields
aws scheduler update-schedule --name datapond-node-stop  --state DISABLED ...
```

**Preserved (untouched):** S3 bucket `datapond-iceberg` (all data + warehouse + athena results),
ECR images (`datapond-backend`, `datapond-frontend`), Glue/Athena catalog, Secrets Manager,
Route53 domain `datapond.csg.fitcloud.co.kr`, the Helm release manifest, and Aurora data
(stopped, not deleted).

Image tags running as of 2026-08-24 (Helm revision 59): backend `2.3.0-0a5fbfa`, frontend
`2.3.0-e3719b2`. Always confirm with the command in step 5 rather than trusting this line —
a backend-only or frontend-only deploy moves one tag and not the other.

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

> **Update 2026-07-27:** re-confirmation completed as a decision note — see
> `CONCEPT_RECONFIRMATION.md` (v6 direction: governed data-access layer for agents/AI apps,
> demo-armed demand validation, ontology demand-gated). Restart is gated on §5.2 of that note.

Re-confirmation covered the open strategic questions surfaced in that cycle:
- **Positioning** — lead with governance + portability (not "AI Data Foundation" breadth, not RAG).
- **Ontology scope** — validated as a *governance + relationship + jargon-vertical* play, **not**
  a general "better search" play (see `ONTOLOGY_FEASIBILITY_REPORT.md`; concept layer is
  self-serve-feasible, relations are the weak spot, retrieval lift is conditional).
- **Business model** — product-only pivot hinges on self-serve ontology (partially validated) +
  a hosted tier + a PLG-friendly segment; services (FDE) is a trap to avoid.
- **Next gate (before rebuild):** validate **demand** with a design partner in one jargon-heavy
  regulated vertical (medical coding / legal / finance) — do not build ahead of demand.

Restart is warranted once the concept + a design-partner demand signal are confirmed.
