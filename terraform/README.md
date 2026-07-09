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
    terraform plan  -var vpc_id=vpc-xxx -var 'db_subnet_ids=["subnet-a","subnet-b"]' \
                    -var app_security_group_id=sg-xxx -var db_master_password=...
    terraform apply <same vars>

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
