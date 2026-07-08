# DataPond AWS MVP — Terraform

Provisions S3, IAM (Bedrock + S3), and Aurora pgvector for the DataPond AWS MVP.

## State backend (one-time)
Terraform state lives in S3 (versioned, encrypted). Bootstrap the state bucket once:

    cd bootstrap && terraform init && terraform apply -var aws_region=us-east-1 && cd ..

Then `terraform init` in this directory uses the S3 backend. Migrating an existing
local state: `terraform init -migrate-state`. See bootstrap/README.md.

## Apply
    terraform init
    terraform validate
    terraform plan  -var vpc_id=vpc-xxx -var 'db_subnet_ids=["subnet-a","subnet-b"]' \
                    -var app_security_group_id=sg-xxx -var db_master_password=...
    terraform apply <same vars>

## Manual prerequisite — enable Bedrock model access (one-time, per region)
In the AWS console → Bedrock → Model access, enable:
- Amazon Titan Text Embeddings V2 (amazon.titan-embed-text-v2:0)
- Anthropic Claude (Haiku + Sonnet) — the model ids in values-aws.yaml

## After apply
- Attach output `bedrock_s3_instance_profile` to the K3s EC2 instance.
- Set Helm `externalDatabase.host` to the `aurora_endpoint` output (Task 5).
