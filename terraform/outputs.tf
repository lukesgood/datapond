output "bucket_name"                 { value = aws_s3_bucket.data.bucket }
output "bedrock_s3_instance_profile" { value = aws_iam_instance_profile.app.name }
