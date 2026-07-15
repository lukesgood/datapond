# AWS-native observability dashboard + cost alarm for the metrics the backend
# emits (app.metrics → CloudWatch namespace var.cloudwatch_metrics_namespace).
# Turns the raw metrics into something watchable, and surfaces Athena spend as
# dollars (BytesScanned ÷ 1 TB × $5). No agents, no node load.
#
# REGION COUPLING: CloudWatch metrics are regional. The backend emits into the
# region from its Helm `s3.region` (metrics.py reads S3_REGION), while these
# resources are created in the provider's var.aws_region. Keep the two equal —
# if they diverge, this dashboard/alarm watch an empty namespace in the wrong
# region. Both default to us-east-1.

variable "cloudwatch_metrics_namespace" {
  type        = string
  default     = "DataPond"
  description = "Must match backend.cloudwatchMetrics.namespace (Helm) and the cloudwatch:namespace IAM condition in iam.tf."
}

variable "athena_daily_scan_alarm_tb" {
  type        = number
  default     = 1
  description = "Alarm when Athena BytesScanned exceeds this many TB in a day (~$5/TB). Set 0 to disable the alarm."
}

variable "alarm_sns_topic_arn" {
  type        = string
  default     = ""
  description = "Pre-existing SNS topic ARN to notify on alarm. Ignored when alarm_email is set (a topic is created). Empty + no alarm_email = alarm changes state only."
}

variable "alarm_email" {
  type        = string
  default     = ""
  description = "Email to notify on alarms. When set, a `<prefix>-alarms` SNS topic + email subscription are created (the recipient must confirm the AWS subscription email once)."
}

# Alarm notification topic — created only when an alarm_email is provided.
resource "aws_sns_topic" "alarms" {
  count = var.alarm_email == "" ? 0 : 1
  name  = "${var.name_prefix}-alarms"
}

resource "aws_sns_topic_subscription" "alarm_email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  cw_ns          = var.cloudwatch_metrics_namespace
  athena_scan_th = var.athena_daily_scan_alarm_tb * 1000000000000 # TB → bytes
  # Prefer the topic we create for alarm_email; else a pre-existing ARN; else none.
  # `one()` yields null when the topic isn't created (count=0) — avoids the
  # `[0]`-on-count-0 index error.
  sns_from_email  = one(aws_sns_topic.alarms[*].arn)
  alarm_topic_arn = local.sns_from_email != null ? local.sns_from_email : var.alarm_sns_topic_arn
}

resource "aws_cloudwatch_dashboard" "datapond" {
  dashboard_name = "${var.name_prefix}-foundation"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        x    = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "AI usage — RAG queries & embeddings"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            [local.cw_ns, "RagQuery", { label = "RAG queries" }],
            [local.cw_ns, "EmbeddingCount", { label = "Embeddings" }],
          ]
        }
      },
      {
        type = "metric"
        x    = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Athena queries"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            [local.cw_ns, "QueryCount", "Engine", "Athena", { label = "Athena queries" }],
          ]
        }
      },
      {
        type = "metric"
        x    = 0, y = 6, width = 24, height = 6
        properties = {
          title  = "Athena scan cost (estimated USD, $5/TB)"
          region = var.aws_region
          view   = "timeSeries"
          period = 3600
          metrics = [
            [local.cw_ns, "BytesScanned", "Engine", "Athena", { id = "bytes", stat = "Sum", visible = false }],
            [{ expression = "bytes / 1000000000000 * 5", label = "Estimated cost (USD)", id = "cost" }],
          ]
        }
      },
    ]
  })
}

# Cost guardrail: alarm when a day's Athena scan crosses the threshold.
resource "aws_cloudwatch_metric_alarm" "athena_daily_scan" {
  count               = var.athena_daily_scan_alarm_tb > 0 ? 1 : 0
  alarm_name          = "${var.name_prefix}-athena-daily-scan"
  alarm_description   = "Athena BytesScanned over 1 day exceeded ${var.athena_daily_scan_alarm_tb} TB (~$${var.athena_daily_scan_alarm_tb * 5}). Investigate for a runaway/unpartitioned scan."
  namespace           = local.cw_ns
  metric_name         = "BytesScanned"
  dimensions          = { Engine = "Athena" }
  statistic           = "Sum"
  period              = 86400 # 1 day
  evaluation_periods  = 1
  threshold           = local.athena_scan_th
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_topic_arn == "" ? [] : [local.alarm_topic_arn]
  ok_actions          = local.alarm_topic_arn == "" ? [] : [local.alarm_topic_arn]
}

output "cloudwatch_dashboard_name" {
  value = aws_cloudwatch_dashboard.datapond.dashboard_name
}

output "alarm_sns_topic_arn" {
  value       = local.alarm_topic_arn
  description = "SNS topic wired to the CloudWatch alarms (empty when no alarm_email / pre-existing ARN)."
}
