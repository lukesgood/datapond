# Backups for the node's root volume.
#
# Aurora has PITR and S3 has versioning, but the root volume — the K3s datastore, every
# Kubernetes Secret, and the local-path PVCs — had no backup at all: `describe-snapshots`
# returned zero and nothing scheduled one. Losing it means rebuilding the cluster by hand.
#
# The snapshot runs after the weekday stop (scheduler.tf stops the node at
# var.schedule_stop_cron, 18:00 Asia/Seoul = 09:00 UTC), so it captures a stopped volume:
# no in-flight writes to the K3s datastore. DLM cron is UTC only, hence the offset here
# rather than a timezone field.

variable "root_snapshot_enabled" {
  type        = bool
  default     = true
  description = "Daily EBS snapshots of the node's root volume via DLM."
}

variable "root_snapshot_cron_utc" {
  type        = string
  default     = "cron(30 10 * * ? *)"
  description = "When to snapshot the root volume, in UTC (default 10:30 UTC = 19:30 KST, after the 18:00 KST stop)."
}

variable "root_snapshot_retention" {
  type        = number
  default     = 7
  description = "How many root-volume snapshots to keep (DLM deletes the oldest beyond this)."
}

data "aws_iam_policy_document" "dlm_assume" {
  count = var.root_snapshot_enabled ? 1 : 0
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dlm" {
  count              = var.root_snapshot_enabled ? 1 : 0
  name               = "${var.name_prefix}-dlm-role"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume[0].json
}

# The AWS-managed policy for this exact job: create/delete/tag snapshots, nothing else.
resource "aws_iam_role_policy_attachment" "dlm" {
  count      = var.root_snapshot_enabled ? 1 : 0
  role       = aws_iam_role.dlm[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "root" {
  count = var.root_snapshot_enabled ? 1 : 0
  # DLM allows only letters, digits, spaces, underscores and hyphens here; an em
  # dash is rejected by the API ("invalid value for description").
  description        = "${var.name_prefix} node root volume daily snapshot"
  execution_role_arn = aws_iam_role.dlm[0].arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]
    # Volumes are selected by tag, which is why ec2.tf tags the root volume. A policy
    # targeting the instance would snapshot every attached volume; there is only one,
    # and naming the volume keeps that true if a data volume is ever added.
    target_tags = { Backup = "daily" }

    schedule {
      name = "daily"
      create_rule {
        cron_expression = var.root_snapshot_cron_utc
      }
      retain_rule {
        count = var.root_snapshot_retention
      }
      # The snapshot inherits the volume's tags, so a restore can tell what it was.
      copy_tags = true
      tags_to_add = {
        SnapshotCreator = "dlm"
        Source          = "${var.name_prefix}-k3s-root"
      }
    }
  }
}

output "root_snapshot_policy_id" {
  value       = one(aws_dlm_lifecycle_policy.root[*].id)
  description = "DLM policy taking daily snapshots of the node root volume (null when disabled)."
}
