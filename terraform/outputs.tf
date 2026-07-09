output "bucket_name" { value = aws_s3_bucket.data.bucket }
output "bedrock_s3_instance_profile" { value = aws_iam_instance_profile.app.name }
output "aurora_endpoint" { value = aws_rds_cluster.aurora.endpoint }
output "litellm_bedrock_role_arn" { value = local.irsa_enabled ? aws_iam_role.litellm_bedrock[0].arn : "" }
output "critical_secrets_arn" { value = aws_secretsmanager_secret.critical.arn }
output "lakehouse_s3_role_arn" { value = local.irsa_enabled ? aws_iam_role.lakehouse_s3[0].arn : "" }
output "ecr_backend_repo_url" { value = aws_ecr_repository.backend.repository_url }
output "ecr_frontend_repo_url" { value = aws_ecr_repository.frontend.repository_url }
