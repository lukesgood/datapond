# Terraform state bootstrap

Creates the S3 bucket that stores the main stack's remote state. Run ONCE.

    cd terraform/bootstrap
    terraform init
    terraform apply -var aws_region=us-east-1      # creates datapond-terraform-state

Then in the main stack (../), `terraform init` will use the S3 backend; if migrating
from an existing local state, run `terraform init -migrate-state`.

The bucket name must match the `backend "s3"` block in ../main.tf
(`datapond-terraform-state`). To use a different name, set `-var state_bucket_name=…`
here AND `terraform init -backend-config="bucket=…"` in the main stack.
