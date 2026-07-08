resource "aws_db_subnet_group" "aurora" {
  name       = "${var.name_prefix}-aurora"
  subnet_ids = var.db_subnet_ids
}

resource "aws_security_group" "aurora" {
  name   = "${var.name_prefix}-aurora-sg"
  vpc_id = var.vpc_id

  ingress {
    description     = "Postgres from app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.app_security_group_id]
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
  engine_version         = "15.4"                 # pgvector available (>= 15.3)
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
