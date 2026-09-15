# DataPond AWS Single-Node Reference — Terraform

This stack provisions the infrastructure used by the current **AWS Single-Node Reference**. It is an EC2/K3s reference connected to managed AWS adapters; it does not create EKS.

## Resources created

- EC2 application node with K3s bootstrap, Elastic IP, and SSM-only administration
- Aurora PostgreSQL Serverless v2 with pgvector-compatible application schema
- versioned S3 data bucket and S3 Terraform-state bootstrap bucket
- ECR backend/frontend repositories
- IAM instance profile and optional IRSA roles when an external EKS OIDC provider is supplied
- Route53 record and certificate bootstrap support
- Secrets Manager critical-secret recovery vault
- CloudWatch/SNS alarms and optional start/stop scheduler
- security groups and related networking attachments

## Not created

- EKS cluster or node groups
- EMR Serverless
- S3 Tables
- Lake Formation
- OpenSearch Serverless/AOSS
- MWAA
- MSK/Managed Flink
- DataZone
- AWS Marketplace packaging/billing
- CDK deployment

These remain future adapters/profiles. `values-aws.yaml` also does not create them.

## State backend

The one-time bootstrap stack creates a versioned/encrypted state bucket named with the AWS account ID.

```bash
cd terraform/bootstrap
terraform init
terraform apply -var aws_region=us-east-1
STATE_BUCKET=$(terraform output -raw state_bucket_name)

cd ..
terraform init \
  -backend-config="bucket=$STATE_BUCKET" \
  -backend-config="region=us-east-1"
```

For an existing local state, add `-migrate-state` after reviewing the target bucket.

## Deployment inputs

| Variable | Required | Purpose |
|---|---|---|
| `domain` | yes | application hostname and Route53 record |
| `route53_zone_id` | yes | hosted zone for DNS and certificate validation |
| `acme_email` | yes | Let's Encrypt account contact |
| `db_subnet_ids` | conditional | defaults to the first two discovered subnets; override for a custom VPC, deterministic placement, or when discovery cannot provide two subnets in different AZs |
| `db_master_password` | yes | Aurora master password; pass securely |

`vpc_id`, `subnet_id`, and `db_subnet_ids` may be omitted to use the selected/default
VPC behavior. Aurora still requires two subnets in different Availability Zones, so
inspect the discovered network and provide `db_subnet_ids` explicitly when that
constraint is not met. Review `allowed_cidrs`; its permissive default is unsuitable for
every environment. The plan example below pins database subnets for deterministic
placement; they are not universally required inputs.

## Apply

```bash
cd terraform
terraform fmt -check -recursive
terraform validate

terraform plan \
  -var domain=datapond.example.com \
  -var route53_zone_id=Z0123456789ABCDEF \
  -var acme_email=ops@example.com \
  -var 'db_subnet_ids=["subnet-a","subnet-b"]' \
  -var db_master_password='<strong-random-password>'

terraform apply <the-same-vars>
```

Review the plan before applying. This creates billable resources and modifies networking, IAM, DNS, storage, and databases.

### Planning against an existing deployment

A deployment that is already running has inputs that differ from the defaults, and a
plan without them proposes to undo that deployment: replace the node, delete the
Route53 record, drop the alarm's notification topic, destroy the GitHub OIDC role.
Keep those inputs in a gitignored `live.tfvars` (see `live.tfvars` rules in
`.gitignore`) and store a copy next to the state, so the next operator plans against
the same inputs:

```bash
aws s3 cp live.tfvars "s3://$STATE_BUCKET/datapond/live.tfvars" --sse AES256   # after editing
aws s3 cp "s3://$STATE_BUCKET/datapond/live.tfvars" live.tfvars                # before planning
terraform plan -var-file=live.tfvars
```

It holds no secret. `db_master_password` stays out of it: pass it through
`TF_VAR_db_master_password` and do not keep a saved plan file, which embeds it.

An unexplained change in that plan is drift. Settle it in code or in `live.tfvars`
before any apply, rather than applying a plan with changes nobody can account for.


## Bedrock prerequisite

Terraform grants IAM permission but cannot grant account/region model access. Enable the configured Titan, Claude, and optional rerank models in Bedrock before acceptance testing. See [AWS_BEDROCK_SETUP.md](../docs/AWS_BEDROCK_SETUP.md).

## Deploy the application

Use `helm/datapond/values-prod-single.yaml`, not `values-aws.yaml`:

```bash
BUCKET=$(terraform output -raw bucket_name)
helm upgrade --install datapond helm/datapond -n datapond \
  --values helm/datapond/values-prod-single.yaml \
  --set externalDatabase.host=$(terraform output -raw aurora_endpoint) \
  --set backend.image.repository=$(terraform output -raw ecr_backend_repo_url) \
  --set frontend.image.repository=$(terraform output -raw ecr_frontend_repo_url) \
  --set-string catalog.glueWarehouse="s3://$BUCKET/warehouse" \
  --set-string catalog.athenaOutputLocation="s3://$BUCKET/athena-results/" \
  --set ingress.domain=datapond.example.com \
  --set postgres.auth.password='<same Aurora master password>'
```

The database password supplied to Helm must match Aurora. Follow the full secret ordering, ECR, TLS, and verification procedure in [DEPLOY_SINGLE_NODE.md](../docs/DEPLOY_SINGLE_NODE.md).

## Backups

| What | How | Retention |
|---|---|---|
| Aurora | automated backups + PITR (`db_backup_retention_period`) | 14 days |
| S3 data bucket | versioning, with noncurrent expiry | 90 days |
| Node root volume | DLM daily snapshot (`dlm.tf`), taken after the evening stop so the volume is quiescent | 7 snapshots |

The root volume is the only copy of the K3s datastore, every Kubernetes Secret, and the
local-path PVCs. It had no backup at all until `dlm.tf`; `root_snapshot_enabled=false`
turns the schedule off, and the volume is selected by its `Backup = daily` tag
(`ec2.tf`), not by instance id.

## Availability and recovery

This reference intentionally uses one EC2/K3s application node. Aurora and S3 are managed/durable, but the application node is not HA. The operating model is fast rebuild:

1. restore/reconcile Aurora if needed;
2. restore `ENCRYPTION_KEY`, JWT, and internal API key from Secrets Manager before backend startup;
3. redeploy Helm with the restored database endpoint;
4. run the AWS RAG acceptance test.

See [DISASTER_RECOVERY.md](../docs/DISASTER_RECOVERY.md).

## Validation

```bash
terraform fmt -check -recursive
terraform validate
terraform -chdir=bootstrap validate
```

After apply, validate the full S3 → Bedrock → pgvector → cited RAG path with [AWS_MVP_RUNBOOK.md](../docs/AWS_MVP_RUNBOOK.md). Glue/Athena claims require their optional acceptance section.

## Teardown

Aurora deletion protection is enabled by default. A planned teardown requires:

1. apply with `db_deletion_protection=false`;
2. decide whether to retain or empty versioned S3 data;
3. preserve required snapshots and critical secrets;
4. run `terraform destroy` with the same required variables.

A fixed final snapshot identifier can conflict with a previous destroy. Rename/remove the previous snapshot or use `db_skip_final_snapshot=true` only for disposable environments where data loss is acceptable.

Do not treat teardown as routine cleanup for a production environment; confirm retention and recovery requirements first.
