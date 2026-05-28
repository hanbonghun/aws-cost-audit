output "iam_role_arn" {
  description = "IAM role ARN to set as GitHub secret AWS_ROLE_ARN"
  value       = aws_iam_role.audit.arn
}

output "s3_bucket_name" {
  description = "S3 bucket name to set as GitHub secret S3_REPORT_BUCKET"
  value       = aws_s3_bucket.reports.bucket
}

output "s3_bucket_arn" {
  description = "S3 bucket ARN (for reference)"
  value       = aws_s3_bucket.reports.arn
}

output "sns_topic_arn" {
  description = "SNS topic ARN to set as GitHub secret SNS_TOPIC_ARN"
  value       = aws_sns_topic.reports.arn
}

output "github_actions_setup" {
  description = "Copy/paste guide to set up GitHub repository secrets"
  value = <<-EOT
    Set these secrets in GitHub Settings → Secrets and variables → Actions:

      AWS_ROLE_ARN      = ${aws_iam_role.audit.arn}
      S3_REPORT_BUCKET  = ${aws_s3_bucket.reports.bucket}
      SNS_TOPIC_ARN     = ${aws_sns_topic.reports.arn}
      AWS_REGION        = ${var.region}

    Optional (only if using Slack):
      SLACK_WEBHOOK_URL = https://hooks.slack.com/services/...
  EOT
}
