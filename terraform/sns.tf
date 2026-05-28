resource "aws_sns_topic" "reports" {
  name              = "${var.name_prefix}-reports"
  display_name      = "AWS Cost Audit Reports"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "email" {
  for_each = toset(var.notification_emails)

  topic_arn = aws_sns_topic.reports.arn
  protocol  = "email"
  endpoint  = each.value
}
