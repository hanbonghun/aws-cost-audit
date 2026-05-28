variable "region" {
  description = "AWS region for management resources (S3, SNS). 데이터 수집은 모든 opted-in 리전에서 수행."
  type        = string
  default     = "ap-northeast-2"
}

variable "name_prefix" {
  description = "Resource name prefix"
  type        = string
  default     = "aws-cost-audit"
}

variable "github_org" {
  description = "GitHub organization or user that owns the repo"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (without org)"
  type        = string
  default     = "aws-cost-audit"
}

variable "github_branch" {
  description = "Branch allowed to assume the IAM role. Use '*' for any branch."
  type        = string
  default     = "main"
}

variable "report_retention_days" {
  description = "S3 report retention before expiration"
  type        = number
  default     = 365
}

variable "notification_emails" {
  description = "List of emails subscribed to the monthly audit SNS topic"
  type        = list(string)
  default     = []
}

variable "enable_budget_alarm" {
  description = "Create AWS Budgets monthly alarm"
  type        = bool
  default     = true
}

variable "monthly_budget_usd" {
  description = "Monthly budget threshold for AWS Budgets alarm"
  type        = number
  default     = 5000
}

variable "enable_cost_anomaly_detection" {
  description = "Create Cost Anomaly Detection monitor"
  type        = bool
  default     = true
}

variable "anomaly_threshold_usd" {
  description = "Minimum impact (USD) to trigger Cost Anomaly Detection alert"
  type        = number
  default     = 100
}
