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
  type = string
  # Existing VPC (Aurora + the single-node EC2 both live here). Default "" ⇒ the account
  # default VPC is used via data.aws_vpc.selected (see ec2.tf), which both the EC2
  # node/subnet lookups and aurora.tf's security group now share.
  default = ""
}

variable "db_subnet_ids" {
  type = list(string) # >= 2 subnets for Aurora, in different AZs
  # Default [] ⇒ aurora.tf's local.db_subnet_ids falls back to the first 2 subnets
  # discovered in the default VPC (data.aws_subnets.public, see ec2.tf). The default VPC
  # gives one subnet per AZ, so slice(...,0,2) spans 2 AZs — good enough for a dev/PoC
  # deploy. A custom VPC with fewer than 2 AZ-distinct subnets MUST set this explicitly.
  default = []
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

# ── Off-hours cost (Aurora Serverless v2 min ACU) ──────────────────────────
variable "db_min_acu" {
  type = number
  # 0 = scale-to-zero (Aurora Serverless v2 "auto-pause"), which needs a recent-enough
  # Postgres engine version (see var.db_engine_version) — if the engine rejects 0, set
  # this to 0.5 (the pre-auto-pause floor) instead. Paired with the node's weekday-hours
  # scheduler (scheduler.tf), this is what actually removes off-hours DB compute cost —
  # stopping the EC2 node alone doesn't stop Aurora from billing at min ACU.
  default = 0
}

variable "db_max_acu" {
  type    = number
  default = 4 # unchanged ceiling; scales up to this under load regardless of db_min_acu
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

variable "instance_type" {
  type    = string
  default = "m6i.xlarge" # 4 vCPU / 16 GB — headroom over the t3.xlarge that ran foundation
}

variable "subnet_id" {
  type    = string
  default = "" # Public subnet for the node. Default "" ⇒ first default-VPC subnet (data lookup).
}

variable "domain" {
  type    = string
  default = "" # e.g. datapond.example.com — the app hostname. Required at deploy time.
}

variable "allowed_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"] # Restrict to a customer CIDR in production if desired.
}

variable "acme_email" {
  type    = string
  default = "" # Let's Encrypt account email (cert-manager ClusterIssuer). Required at deploy time.
}

variable "app_version" {
  type    = string
  default = "2.3.0" # image tag pushed to ECR by CI; matches helm Chart.yaml appVersion
}

# ── Spot + weekday-hours scheduling (cost-optimized, matches existing pattern) ──
variable "use_spot" {
  type    = bool
  default = true # persistent spot node (stoppable). false ⇒ on-demand.
}
variable "schedule_enabled" {
  type    = bool
  default = true # start/stop the node on a weekday-hours schedule
}
variable "schedule_start_cron" {
  type    = string
  default = "cron(30 7 ? * MON-FRI *)" # 07:30 Mon-Fri (see schedule_timezone)
}
variable "schedule_stop_cron" {
  type    = string
  default = "cron(0 18 ? * MON-FRI *)" # 18:00 Mon-Fri
}
variable "schedule_timezone" {
  type    = string
  default = "Asia/Seoul" # KST
}
