variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "bucket_name" {
  type = string
  # S3 bucket names are GLOBALLY unique. "datapond-iceberg" is free today but generic —
  # if it collides, override with an account-scoped name, e.g.
  #   -var bucket_name=datapond-iceberg-<account-id>
  # Keep the Helm `storage.bucket` (values-aws.yaml) in sync with whatever you set here.
  default = "datapond-iceberg"
}

variable "name_prefix" {
  type    = string
  default = "datapond"
}

variable "vpc_id" {
  type = string # existing PoC VPC
}

variable "db_subnet_ids" {
  type = list(string) # >= 2 subnets for Aurora
}

variable "app_security_group_id" {
  type = string # K3s EC2 SG (DB ingress source)
}

variable "db_master_password" {
  type      = string
  sensitive = true
}

variable "db_engine_version" {
  type = string
  # Aurora PostgreSQL version. AWS RETIRES minor versions (15.4 was pulled → apply failed
  # with "Cannot find version 15.4"), so this is a var, not a literal. pgvector needs >= 15.3;
  # Serverless v2 needs >= 13.6. Check availability: aws rds describe-db-engine-versions
  # --engine aurora-postgresql --query 'DBEngineVersions[].EngineVersion'.
  default = "15.10"
}

# ── Backup / DR (P0-5) ──────────────────────────────────────────────────────
variable "db_backup_retention_period" {
  type    = number
  default = 14 # PITR window (days) = RPO horizon
}

variable "db_deletion_protection" {
  type    = bool
  default = true # block destroy/console delete
}

variable "db_skip_final_snapshot" {
  type    = bool
  default = false # take a final snapshot on destroy
}

variable "db_preferred_backup_window" {
  type    = string
  default = "03:00-04:00" # UTC
}

variable "db_preferred_maintenance_window" {
  type    = string
  default = "sun:04:30-sun:05:30" # UTC
}

variable "db_kms_key_id" {
  type    = string
  default = null # optional CMK; null ⇒ AWS-managed aws/rds key
}

variable "eks_oidc_provider_arn" {
  type    = string
  default = "" # arn:aws:iam::<acct>:oidc-provider/oidc.eks.<region>.amazonaws.com/id/XXXX
}

variable "eks_oidc_provider_url" {
  type    = string
  default = "" # oidc.eks.<region>.amazonaws.com/id/XXXX (no https://)
}

variable "k8s_namespace" {
  type    = string
  default = "datapond"
}

variable "litellm_sa_name" {
  type    = string
  default = "litellm"
}

variable "s3_noncurrent_version_expiration_days" {
  type    = number
  default = 90 # cull old object versions
}

variable "lakehouse_sa_names" {
  type    = list(string)
  default = ["datapond-backend", "datapond-trino", "datapond-spark", "datapond-jupyter", "datapond-mlflow", "datapond-polaris"]
}

variable "route53_zone_id" {
  type    = string
  default = "" # Hosted zone ID for var.domain; required at deploy time for DNS-01 + the A record.
}
