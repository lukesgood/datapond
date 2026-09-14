# GitHub Actions OIDC → AWS role for .github/workflows/ecr-push.yml (aws-actions/
# configure-aws-credentials with role-to-assume). Entirely opt-in: everything here is
# gated on var.github_oidc_enabled (default false) so a default apply is unaffected.
#
# To enable:
#   1. terraform apply -var github_oidc_enabled=true
#      (if the account already has a GitHub OIDC provider — only one can exist per URL —
#      also pass -var github_oidc_create_provider=false to reuse it via a data lookup)
#   2. Put the `ecr_push_role_arn` output value into the repo's GitHub secret
#      ECR_PUSH_ROLE_ARN (Settings → Secrets and variables → Actions).

variable "github_oidc_enabled" {
  type    = bool
  default = false # master switch for the ECR-push OIDC role below
}

variable "github_ecr_push_enabled" {
  type = bool
  # The ecr_push role serves ecr-push.yml, which only builds images. deploy-aws.yml builds,
  # pushes and deploys with the cd role below, so enabling OIDC for deploys should not also
  # hand out an unused push credential. Turn this on only if ecr-push.yml is used.
  default = false
}

locals {
  ecr_push_enabled = var.github_oidc_enabled && var.github_ecr_push_enabled
}

variable "github_oidc_create_provider" {
  type = bool
  # true ⇒ create the aws_iam_openid_connect_provider for token.actions.githubusercontent.com.
  # AWS allows only ONE OIDC provider per URL per account — if a provider for GitHub Actions
  # already exists (e.g. created by another stack), set this to false to look it up instead
  # via a data source.
  default = true
}

variable "github_repo" {
  type    = string
  default = "lukesgood/datapond" # trust is scoped to repo:<github_repo>:* (any branch/ref)
}

# GitHub's OIDC token-signing certificate thumbprint. AWS's IAM OIDC provider stopped
# actually validating this against GitHub in 2023 (it now trusts GitHub's well-known root
# CAs directly), but the field is still required by the resource schema.
locals {
  github_oidc_thumbprints = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.github_oidc_enabled && var.github_oidc_create_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = local.github_oidc_thumbprints
}

data "aws_iam_openid_connect_provider" "github_existing" {
  count = var.github_oidc_enabled && !var.github_oidc_create_provider ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = !var.github_oidc_enabled ? "" : (
    var.github_oidc_create_provider
    ? aws_iam_openid_connect_provider.github[0].arn
    : data.aws_iam_openid_connect_provider.github_existing[0].arn
  )
}

data "aws_iam_policy_document" "ecr_push_assume" {
  count = local.ecr_push_enabled ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "ecr_push" {
  count              = local.ecr_push_enabled ? 1 : 0
  name               = "${var.name_prefix}-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.ecr_push_assume[0].json
}

data "aws_iam_policy_document" "ecr_push" {
  count = local.ecr_push_enabled ? 1 : 0
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # GetAuthorizationToken is account-wide, cannot be resource-scoped
  }
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
    ]
    resources = [
      aws_ecr_repository.backend.arn,
      aws_ecr_repository.frontend.arn,
    ]
  }
}

resource "aws_iam_role_policy" "ecr_push" {
  count  = local.ecr_push_enabled ? 1 : 0
  name   = "${var.name_prefix}-ecr-push-policy"
  role   = aws_iam_role.ecr_push[0].id
  policy = data.aws_iam_policy_document.ecr_push[0].json
}

output "ecr_push_role_arn" {
  value = local.ecr_push_enabled ? aws_iam_role.ecr_push[0].arn : ""
}

# ── CD role for .github/workflows/deploy-aws.yml ──────────────────────────────────────
# The ecr_push role above covers ecr-push.yml, which only builds images. deploy-aws.yml
# does three more things — stages a chart bundle in S3, tells the node to fetch it over
# SSM, and reads the command's result — so it needs its own role rather than a widened
# ECR one. Same master switch (var.github_oidc_enabled) and the same OIDC provider.
#
# This role can run shell as root on the production node. Two things keep that bounded:
# ssm:SendCommand is scoped to the one instance and the one document, and the trust is
# scoped to a single branch rather than the whole repo — dispatching a deploy from a
# side branch is not a thing that should work by default. Widen github_cd_ref if it must.

variable "github_cd_ref" {
  type    = string
  default = "refs/heads/main"
  # The git ref a deploy may be dispatched FROM. deploy-aws.yml still takes an `ref`
  # input for which code to build; this constrains where the workflow itself is run.
}

variable "deploy_bucket" {
  type    = string
  default = "" # defaults to the data bucket below; the node already reads/writes it
}

locals {
  deploy_bucket_name = var.deploy_bucket != "" ? var.deploy_bucket : aws_s3_bucket.data.bucket
}

data "aws_iam_policy_document" "cd_assume" {
  count = var.github_oidc_enabled ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:${var.github_cd_ref}"]
    }
  }
}

resource "aws_iam_role" "cd" {
  count              = var.github_oidc_enabled ? 1 : 0
  name               = "${var.name_prefix}-cd"
  description        = "GitHub Actions deploy-aws.yml: build, stage, and roll the node"
  assume_role_policy = data.aws_iam_policy_document.cd_assume[0].json
}

data "aws_iam_policy_document" "cd" {
  count = var.github_oidc_enabled ? 1 : 0
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # account-wide by API design, cannot be resource-scoped
  }
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
    ]
    resources = [aws_ecr_repository.backend.arn, aws_ecr_repository.frontend.arn]
  }
  statement {
    sid       = "StageChartBundle"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${local.deploy_bucket_name}/deploy/*"]
  }
  statement {
    sid     = "RollTheNode"
    actions = ["ssm:SendCommand"]
    # Scoped by tag, not by aws_instance.node.arn. Referencing the instance made this
    # policy depend on it, so a `terraform apply -target` of the CD role pulled the node
    # into the plan — and while the live node has drifted from this module, that plan
    # replaces it. A tag also survives the spot or AMI-driven rebuild that deploy-aws.yml
    # exists to handle.
    resources = ["arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/*"]
    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Name"
      values   = ["${var.name_prefix}-k3s"]
    }
  }
  statement {
    # The document is a separate resource on the same call and carries no tag, so it
    # cannot share the tag condition above.
    sid       = "RunShellDocument"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript"]
  }
  statement {
    sid       = "ReadCommandResult"
    actions   = ["ssm:GetCommandInvocation"]
    resources = ["*"] # the command id is minted per run and cannot be named in advance
  }
}

resource "aws_iam_role_policy" "cd" {
  count  = var.github_oidc_enabled ? 1 : 0
  name   = "${var.name_prefix}-cd-policy"
  role   = aws_iam_role.cd[0].id
  policy = data.aws_iam_policy_document.cd[0].json
}

output "cd_role_arn" {
  value       = var.github_oidc_enabled ? aws_iam_role.cd[0].arn : ""
  description = "Put in the repo secret AWS_CD_ROLE_ARN"
}

output "deploy_bucket" {
  value       = local.deploy_bucket_name
  description = "Put in the repo variable DEPLOY_BUCKET"
}
