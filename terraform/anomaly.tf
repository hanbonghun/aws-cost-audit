resource "aws_ce_anomaly_monitor" "service" {
  count = var.enable_cost_anomaly_detection ? 1 : 0

  name              = "${var.name_prefix}-service-monitor"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "service" {
  count = var.enable_cost_anomaly_detection && length(var.notification_emails) > 0 ? 1 : 0

  name      = "${var.name_prefix}-anomaly-sub"
  frequency = "DAILY"
  monitor_arn_list = [
    aws_ce_anomaly_monitor.service[0].arn,
  ]

  dynamic "subscriber" {
    for_each = toset(var.notification_emails)
    content {
      type    = "EMAIL"
      address = subscriber.value
    }
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.anomaly_threshold_usd)]
    }
  }
}
