data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.name_prefix}-app-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "app" {
  statement {
    sid = "S3Data"
    # GetBucketLocation + multipart are required by Athena to verify/write the query
    # results bucket (ATHENA_OUTPUT_LOCATION).
    actions = [
      "s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
      "s3:GetBucketLocation", "s3:ListBucketMultipartUploads", "s3:AbortMultipartUpload",
    ]
    resources = [
      aws_s3_bucket.data.arn,
      "${aws_s3_bucket.data.arn}/*",
    ]
  }
  statement {
    sid       = "BedrockInvoke"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"] # scope to inference-profile ARNs once finalized
  }
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # GetAuthorizationToken is account-wide, cannot be resource-scoped
  }
  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchCheckLayerAvailability",
    ]
    resources = [
      aws_ecr_repository.backend.arn,
      aws_ecr_repository.frontend.arn,
    ]
  }
  statement {
    sid       = "Route53DNS01"
    actions   = ["route53:GetChange"]
    resources = ["arn:aws:route53:::change/*"]
  }
  statement {
    sid       = "Route53Records"
    actions   = ["route53:ChangeResourceRecordSets", "route53:ListResourceRecordSets"]
    resources = ["arn:aws:route53:::hostedzone/${var.route53_zone_id}"]
  }
  statement {
    sid    = "GlueDataCatalog"
    effect = "Allow"
    actions = [
      "glue:GetDatabase", "glue:GetDatabases", "glue:CreateDatabase", "glue:DeleteDatabase",
      "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable",
      "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition",
      "glue:BatchCreatePartition", "glue:CreatePartition", "glue:UpdatePartition", "glue:DeletePartition",
    ]
    resources = ["*"] # Glue ARNs are catalog/db/table-scoped; tighten to datapond* dbs in a follow-up
  }
  statement {
    sid    = "AthenaQuery"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution", "athena:GetQueryExecution",
      "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup",
    ]
    resources = ["*"] # workgroup-scoped; tighten to the primary workgroup ARN in a follow-up
  }
  # docs/DISASTER_RECOVERY.md procedure B re-seeds datapond-secrets from this vault
  # BEFORE the app starts, and it runs on the node (kubectl reaches the cluster from
  # there, not from an operator laptop). Without this the documented recovery cannot
  # execute, and an ENCRYPTION_KEY lost with the cluster makes every connector and
  # provider credential in Aurora permanently undecryptable.
  #
  # Read only, and only this vault. Seeding is a deliberate operator act performed
  # with operator credentials, so PutSecretValue stays off the node.
  statement {
    sid       = "CriticalSecretsRecovery"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [aws_secretsmanager_secret.critical.arn]
  }

  # Only when the vault is encrypted with a customer CMK. Under the AWS-managed key
  # (db_kms_key_id = null, the default) the key policy grants decryption through
  # Secrets Manager itself and this statement must not exist — an empty resource
  # list would make the policy invalid. A CMK without it fails at recovery time,
  # which is the one moment nobody can afford to debug an IAM error.
  dynamic "statement" {
    for_each = var.db_kms_key_id == null ? [] : [var.db_kms_key_id]
    content {
      sid       = "CriticalSecretsDecrypt"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = [statement.value]
    }
  }

  statement {
    sid       = "CloudWatchMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"] # PutMetricData has no resource-level scoping
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["DataPond"]
    }
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "${var.name_prefix}-app-policy"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.name_prefix}-app-profile"
  role = aws_iam_role.app.name
}

resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
