output "bucket_name"                 { value = aws_s3_bucket.data.bucket }
output "bedrock_s3_instance_profile" { value = aws_iam_instance_profile.app.name }
output "aurora_endpoint"             { value = aws_rds_cluster.aurora.endpoint }
