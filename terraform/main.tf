terraform {
  required_version = ">= 1.10" # S3-native state locking (use_lockfile)
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }

  # Remote state — S3 bucket created by terraform/bootstrap (run once). PARTIAL config:
  # bucket + region are NOT hardcoded (a bare "datapond-terraform-state" collides in S3's
  # GLOBAL namespace — it is already taken by another account). Supply them at init:
  #   terraform init \
  #     -backend-config="bucket=$(terraform -chdir=bootstrap output -raw state_bucket_name)" \
  #     -backend-config="region=us-east-1"
  # (bootstrap defaults the bucket to datapond-terraform-state-<account-id>.)
  backend "s3" {
    key          = "datapond/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}
