# Weekday-hours start/stop for the node (cost control). EventBridge Scheduler invokes the
# EC2 start/stop APIs on a cron; the node is persistent spot so stop/start preserves it.
data "aws_iam_policy_document" "scheduler_assume" {
  count = var.schedule_enabled ? 1 : 0
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  count              = var.schedule_enabled ? 1 : 0
  name               = "${var.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume[0].json
}

resource "aws_iam_role_policy" "scheduler" {
  count = var.schedule_enabled ? 1 : 0
  name  = "${var.name_prefix}-scheduler-ec2"
  role  = aws_iam_role.scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ec2:StartInstances", "ec2:StopInstances"]
      Resource = "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/${aws_instance.node.id}"
    }]
  })
}

resource "aws_scheduler_schedule" "start" {
  count                        = var.schedule_enabled ? 1 : 0
  name                         = "${var.name_prefix}-node-start"
  schedule_expression          = var.schedule_start_cron
  schedule_expression_timezone = var.schedule_timezone
  flexible_time_window { mode = "OFF" }
  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:startInstances"
    role_arn = aws_iam_role.scheduler[0].arn
    input    = jsonencode({ InstanceIds = [aws_instance.node.id] })
  }
}

resource "aws_scheduler_schedule" "stop" {
  count                        = var.schedule_enabled ? 1 : 0
  name                         = "${var.name_prefix}-node-stop"
  schedule_expression          = var.schedule_stop_cron
  schedule_expression_timezone = var.schedule_timezone
  flexible_time_window { mode = "OFF" }
  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"
    role_arn = aws_iam_role.scheduler[0].arn
    input    = jsonencode({ InstanceIds = [aws_instance.node.id] })
  }
}
