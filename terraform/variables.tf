variable "aws_region"  { type = string  default = "us-east-1" }
variable "bucket_name" { type = string  default = "datapond-iceberg" }
variable "name_prefix" { type = string  default = "datapond" }
variable "vpc_id"      { type = string }            # existing PoC VPC
variable "db_subnet_ids" { type = list(string) }    # >= 2 subnets for Aurora
variable "app_security_group_id" { type = string }  # K3s EC2 SG (DB ingress source)
variable "db_master_password" { type = string  sensitive = true }
