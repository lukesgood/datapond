# Terraform state bootstrap

Creates the S3 bucket that stores the main stack's remote state. Run ONCE.

    cd terraform/bootstrap
    terraform init
    terraform apply -var aws_region=us-east-1      # creates datapond-terraform-state-<account-id>

The bucket name is account-scoped by default (`datapond-terraform-state-<account-id>`) because
S3 names are GLOBALLY unique — a bare `datapond-terraform-state` collides with another account.
Override with `-var state_bucket_name=…` if needed.

The main stack (../) uses a PARTIAL backend config — its `backend "s3"` block does NOT hardcode a
bucket. Feed this bucket to its init:

    STATE_BUCKET=$(terraform output -raw state_bucket_name)
    cd .. && terraform init -backend-config="bucket=$STATE_BUCKET" -backend-config="region=us-east-1"

If migrating from an existing local state, add `-migrate-state` to that init.
