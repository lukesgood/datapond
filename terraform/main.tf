terraform {
  required_version = ">= 1.10" # S3-native state locking (use_lockfile)
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }

  # Remote state — S3 bucket created by terraform/bootstrap (run once). The bucket
  # name + region are literal here (backend blocks can't use variables); override
  # per-environment with `terraform init -backend-config=...` if needed.
  backend "s3" {
    bucket       = "datapond-terraform-state"
    key          = "datapond/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}
