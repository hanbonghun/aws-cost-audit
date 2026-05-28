# Terraform-managed AWS infrastructure for aws-cost-audit.
#
# Resources:
#   - S3 bucket (reports.tf)        : Storage for monthly audit reports
#   - IAM role + OIDC (iam.tf)      : Read-only role assumable by GitHub Actions
#   - SNS topic (sns.tf)            : Email/Slack notification channel
#   - AWS Budgets (budgets.tf)      : Monthly spend threshold alarm (opt-in)
#   - Cost Anomaly Detection        : Service-level anomaly monitor (opt-in)
#
# State backend is left local by default — for team use, configure remote
# state (S3 + DynamoDB lock) in a separate `backend.tf` file.
