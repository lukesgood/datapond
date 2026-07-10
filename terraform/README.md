# DataPond AWS MVP — Terraform

Provisions S3, IAM (Bedrock + S3), and Aurora pgvector for the DataPond AWS MVP.

## State backend (one-time)
Terraform state lives in S3 (versioned, encrypted). S3 bucket names are GLOBALLY unique,
so the state bucket is named `datapond-terraform-state-<account-id>` (a bare
`datapond-terraform-state` collides — it is already taken by another account). Bootstrap
it once, then point the main stack's partial backend at it:

    cd bootstrap && terraform init && terraform apply -var aws_region=us-east-1
    STATE_BUCKET=$(terraform output -raw state_bucket_name)
    cd ..
    terraform init \
      -backend-config="bucket=$STATE_BUCKET" \
      -backend-config="region=us-east-1"

Migrating an existing local state adds `-migrate-state` to that init. See bootstrap/README.md.

## Apply
    terraform init
    terraform validate
    terraform plan  -var 'db_subnet_ids=["subnet-a","subnet-b"]' -var db_master_password=... \
                    -var domain=... -var route53_zone_id=... -var acme_email=...
    terraform apply <same vars>

`vpc_id`/`subnet_id` are optional — omit them to use the account default VPC (see
`data.aws_vpc.selected` in ec2.tf); the node's security group is wired automatically as
Aurora's DB-ingress source, so no separate app-SG variable is needed.

> **Teardown:** `deletion_protection=true` (default) blocks `terraform destroy` — run
> `terraform apply -var db_deletion_protection=false` first. A second destroy also collides
> on the fixed `final_snapshot_identifier` (`datapond-pg-final-snapshot`) — rename/remove the
> prior snapshot or set `-var db_skip_final_snapshot=true` for a throwaway env.

## Manual prerequisite — enable Bedrock model access (one-time, per region)
In the AWS console → Bedrock → Model access, enable:
- Amazon Titan Text Embeddings V2 (amazon.titan-embed-text-v2:0)
- Anthropic Claude (Haiku + Sonnet) — the model ids in values-aws.yaml

## After apply
- Attach output `bedrock_s3_instance_profile` to the K3s EC2 instance.
- Set Helm `externalDatabase.host` to the `aurora_endpoint` output (Task 5).

## Single-node production

This stack also provisions a full single-node K3s production topology: the EC2 node
(`ec2.tf`) + Elastic IP, ECR repos (`ecr.tf`) for CI-built images, a Route53 A record
(`route53.tf`), and the Secrets Manager DR vault (`secrets.tf`) — on top of the Aurora/S3/
IAM already described above. The end-to-end operator flow (build images via CI, apply
this stack, seed the critical-secrets vault, install the Helm `foundation` profile from
ECR, verify, and tear down) is documented in full in
**[`docs/DEPLOY_SINGLE_NODE.md`](../docs/DEPLOY_SINGLE_NODE.md)** — read that before
running `terraform apply` for a production bring-up.

New vars this topology adds (beyond `db_subnet_ids`/`db_master_password` above):

| Var | Default | Purpose |
|---|---|---|
| `domain` | `""` (required at deploy time) | App hostname, e.g. `datapond.example.com` — Route53 A record + cert-manager cert + ingress. |
| `route53_zone_id` | `""` (required at deploy time) | Hosted zone ID for `var.domain` — the A record and the cert-manager Route53 DNS-01 solver. |
| `acme_email` | `""` (required at deploy time) | Let's Encrypt account contact email (cert-manager `ClusterIssuer`). |
| `instance_type` | `m6i.xlarge` | EC2 instance size for the K3s node (4 vCPU / 16 GB). |
| `allowed_cidrs` | `["0.0.0.0/0"]` | CIDRs allowed to reach the node on 80/443. Narrow to a customer allowlist for a locked-down deploy; port 22 is never opened (SSM-only admin). |
| `app_version` | `2.3.0` | Image tag pulled from ECR; matches `helm/datapond/Chart.yaml` `appVersion` and whatever CI tag `.github/workflows/ecr-push.yml` pushed. |

`domain`/`route53_zone_id`/`acme_email` have empty-string defaults so `terraform plan`/
`validate` work without them, but the Route53 A record (`route53.tf`) and a usable
cert-manager `ClusterIssuer` require all three to be set for a real deploy.
