# Bootstrap: creates the versioned+encrypted S3 bucket that holds the MAIN stack's
# remote state. Run ONCE before `terraform init` in ../ . Its own state is local
# (a single bucket; losing it just means importing the bucket later — no infra orphaned).
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.aws_region }

data "aws_caller_identity" "current" {}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "state_bucket_name" {
  type    = string
  default = "" # empty ⇒ datapond-terraform-state-<account-id> (globally unique; S3 names are global)
}

locals {
  # A bare "datapond-terraform-state" collides in S3's global namespace (it is already
  # taken by another account). Suffix with the account id — matching this account's own
  # convention (datapond-deploy-<acct>, okr-config-<acct>, …). Override via var if needed.
  state_bucket = var.state_bucket_name != "" ? var.state_bucket_name : "datapond-terraform-state-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "state" {
  bucket = local.state_bucket
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "state_bucket_name" { value = aws_s3_bucket.state.bucket }
