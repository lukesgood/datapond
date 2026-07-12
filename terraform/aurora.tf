locals {
  # Aurora needs >= 2 subnets in different AZs. Default VPC gives one subnet per AZ, so
  # slice(...,0,2) on the discovered public subnets (data.aws_subnets.public, ec2.tf) spans
  # 2 AZs. A custom VPC with < 2 AZ-distinct subnets must set var.db_subnet_ids explicitly.
  db_subnet_ids = length(var.db_subnet_ids) > 0 ? var.db_subnet_ids : slice(data.aws_subnets.public.ids, 0, 2)
}

resource "aws_db_subnet_group" "aurora" {
  name       = "${var.name_prefix}-aurora"
  subnet_ids = local.db_subnet_ids
}

resource "aws_security_group" "aurora" {
  name   = "${var.name_prefix}-aurora-sg"
  vpc_id = data.aws_vpc.selected.id

  ingress {
    description     = "Postgres from app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.node.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_rds_cluster" "aurora" {
  cluster_identifier     = "${var.name_prefix}-pg"
  engine                 = "aurora-postgresql"
  engine_mode            = "provisioned"
  engine_version         = var.db_engine_version
  database_name          = "datapond"
  master_username        = "datapond"
  master_password        = var.db_master_password
  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [aws_security_group.aurora.id]
  storage_encrypted      = true
  kms_key_id             = var.db_kms_key_id

  # ── Backup / DR (P0-5) ──
  backup_retention_period      = var.db_backup_retention_period
  preferred_backup_window      = var.db_preferred_backup_window
  preferred_maintenance_window = var.db_preferred_maintenance_window
  copy_tags_to_snapshot        = true
  deletion_protection          = var.db_deletion_protection
  skip_final_snapshot          = var.db_skip_final_snapshot
  final_snapshot_identifier    = "${var.name_prefix}-pg-final-snapshot"

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 4.0
  }
}

resource "aws_rds_cluster_instance" "aurora" {
  identifier         = "${var.name_prefix}-pg-1"
  cluster_identifier = aws_rds_cluster.aurora.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.aurora.engine
  engine_version     = aws_rds_cluster.aurora.engine_version
}
