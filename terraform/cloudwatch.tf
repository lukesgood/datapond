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
  description = "Optional SNS topic ARN to notify on alarm. Empty = alarm changes state only (visible in console, no notification)."
}

locals {
  cw_ns          = var.cloudwatch_metrics_namespace
  athena_scan_th = var.athena_daily_scan_alarm_tb * 1000000000000 # TB → bytes
}

resource "aws_cloudwatch_dashboard" "datapond" {
  dashboard_name = "${var.name_prefix}-foundation"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0, y = 0, width = 12, height = 6
        properties = {
          title   = "AI usage — RAG queries & embeddings"
          region  = var.aws_region
          view    = "timeSeries"
          stat    = "Sum"
          period  = 300
          metrics = [
            [local.cw_ns, "RagQuery", { label = "RAG queries" }],
            [local.cw_ns, "EmbeddingCount", { label = "Embeddings" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12, y = 0, width = 12, height = 6
        properties = {
          title   = "Athena queries"
          region  = var.aws_region
          view    = "timeSeries"
          stat    = "Sum"
          period  = 300
          metrics = [
            [local.cw_ns, "QueryCount", "Engine", "Athena", { label = "Athena queries" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0, y = 6, width = 24, height = 6
        properties = {
          title   = "Athena scan cost (estimated USD, $5/TB)"
          region  = var.aws_region
          view    = "timeSeries"
          period  = 3600
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
  alarm_actions       = var.alarm_sns_topic_arn == "" ? [] : [var.alarm_sns_topic_arn]
  ok_actions          = var.alarm_sns_topic_arn == "" ? [] : [var.alarm_sns_topic_arn]
}

output "cloudwatch_dashboard_name" {
  value = aws_cloudwatch_dashboard.datapond.dashboard_name
}
