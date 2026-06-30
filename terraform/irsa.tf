# Optional IRSA role for the LiteLLM serviceAccount to call Bedrock on EKS.
# Created only when eks_oidc_provider_arn is set (K3s/EC2 PoC uses the instance profile in iam.tf).
locals {
  irsa_enabled = var.eks_oidc_provider_arn != ""
}

data "aws_iam_policy_document" "litellm_irsa_assume" {
  count = local.irsa_enabled ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.eks_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_url}:sub"
      values   = ["system:serviceaccount:${var.k8s_namespace}:${var.litellm_sa_name}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "litellm_bedrock" {
  count              = local.irsa_enabled ? 1 : 0
  name               = "${var.name_prefix}-litellm-bedrock"
  assume_role_policy = data.aws_iam_policy_document.litellm_irsa_assume[0].json
}

data "aws_iam_policy_document" "litellm_bedrock" {
  count = local.irsa_enabled ? 1 : 0
  statement {
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]  # scope to inference-profile ARNs once finalized
  }
}

resource "aws_iam_role_policy" "litellm_bedrock" {
  count  = local.irsa_enabled ? 1 : 0
  name   = "${var.name_prefix}-litellm-bedrock"
  role   = aws_iam_role.litellm_bedrock[0].id
  policy = data.aws_iam_policy_document.litellm_bedrock[0].json
}
