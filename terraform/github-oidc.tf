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
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "ecr_push" {
  count              = var.github_oidc_enabled ? 1 : 0
  name               = "${var.name_prefix}-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.ecr_push_assume[0].json
}

data "aws_iam_policy_document" "ecr_push" {
  count = var.github_oidc_enabled ? 1 : 0
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
  count  = var.github_oidc_enabled ? 1 : 0
  name   = "${var.name_prefix}-ecr-push-policy"
  role   = aws_iam_role.ecr_push[0].id
  policy = data.aws_iam_policy_document.ecr_push[0].json
}

output "ecr_push_role_arn" {
  value = var.github_oidc_enabled ? aws_iam_role.ecr_push[0].arn : ""
}
