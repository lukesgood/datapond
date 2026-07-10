# Single-node K3s production host. Availability = P0-5 backup/restore, not HA (by design).
data "aws_caller_identity" "current" {}

data "aws_vpc" "selected" {
  id      = var.vpc_id != "" ? var.vpc_id : null
  default = var.vpc_id == "" ? true : null
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.selected.id]
  }
}

# Ubuntu 24.04 LTS amd64 (Canonical SSM public parameter — always current).
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

resource "aws_security_group" "node" {
  name        = "${var.name_prefix}-node"
  description = "DataPond single-node K3s: 443/80 in, SSM-only admin (no 22)"
  vpc_id      = data.aws_vpc.selected.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }
  ingress {
    description = "HTTP (Traefik 301 to 443 redirect; TLS via DNS-01, not HTTP-01)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "node" {
  ami                    = data.aws_ssm_parameter.ubuntu.value
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id != "" ? var.subnet_id : data.aws_subnets.public.ids[0]
  vpc_security_group_ids = [aws_security_group.node.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  root_block_device {
    volume_size           = 60
    volume_type           = "gp3"
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/user-data.sh.tftpl", {
    aws_region      = var.aws_region
    domain          = var.domain
    acme_email      = var.acme_email
    route53_zone_id = var.route53_zone_id
    ecr_registry    = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    backend_repo    = aws_ecr_repository.backend.repository_url
    frontend_repo   = aws_ecr_repository.frontend.repository_url
    aurora_host     = aws_rds_cluster.aurora.endpoint
    bucket_name     = aws_s3_bucket.data.bucket
    app_version     = var.app_version
  })

  tags = { Name = "${var.name_prefix}-k3s", managed-by = "terraform" }
}

resource "aws_eip" "node" {
  instance = aws_instance.node.id
  domain   = "vpc"
  tags     = { Name = "${var.name_prefix}-eip" }
}
