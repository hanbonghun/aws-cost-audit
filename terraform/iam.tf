# GitHub OIDC provider for AWS — keyless auth from GitHub Actions.
# If your account already has the GitHub OIDC provider (sub: token.actions.githubusercontent.com),
# import it: terraform import aws_iam_openid_connect_provider.github arn:aws:iam::ACCOUNT:oidc-provider/token.actions.githubusercontent.com

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [
        var.github_branch == "*"
          ? "repo:${var.github_org}/${var.github_repo}:*"
          : "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/${var.github_branch}"
      ]
    }
  }
}

resource "aws_iam_role" "audit" {
  name               = "${var.name_prefix}-reader"
  description        = "Read-only role assumed by GitHub Actions (${var.github_org}/${var.github_repo}) to run AWS cost audits."
  assume_role_policy = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

# Core read-only permissions — covers most describe/list/get
resource "aws_iam_role_policy_attachment" "readonly" {
  role       = aws_iam_role.audit.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/ReadOnlyAccess"
}

# Billing-specific read (Cost Explorer, billing console)
resource "aws_iam_role_policy_attachment" "billing_read" {
  role       = aws_iam_role.audit.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AWSBillingReadOnlyAccess"
}

# Compute Optimizer recommendations
resource "aws_iam_role_policy_attachment" "compute_optimizer_read" {
  role       = aws_iam_role.audit.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/ComputeOptimizerReadOnlyAccess"
}

# Cost Optimization Hub (newer service, optional)
resource "aws_iam_role_policy_attachment" "cost_optimization_hub_read" {
  role       = aws_iam_role.audit.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/CostOptimizationHubReadOnlyAccess"
}

# Trusted Advisor priority (requires Business+ support plan)
resource "aws_iam_role_policy_attachment" "trusted_advisor_read" {
  role       = aws_iam_role.audit.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AWSTrustedAdvisorPriorityReadOnlyAccess"
}

# Inline policy: Cost Explorer + S3 write to report bucket + SNS publish
data "aws_iam_policy_document" "audit_inline" {
  statement {
    sid    = "CostExplorerExplicit"
    effect = "Allow"
    actions = [
      "ce:GetCostAndUsage",
      "ce:GetCostForecast",
      "ce:GetReservationCoverage",
      "ce:GetReservationUtilization",
      "ce:GetSavingsPlansCoverage",
      "ce:GetSavingsPlansUtilization",
      "ce:GetSavingsPlansPurchaseRecommendation",
      "ce:GetReservationPurchaseRecommendation",
      "ce:GetAnomalies",
      "ce:GetCostCategories",
      "ce:ListCostCategoryDefinitions",
      "ce:GetDimensionValues",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ReportBucketWrite"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:PutObjectAcl",
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.reports.arn,
      "${aws_s3_bucket.reports.arn}/*",
    ]
  }

  statement {
    sid    = "SNSPublishReports"
    effect = "Allow"
    actions = [
      "sns:Publish",
    ]
    resources = [aws_sns_topic.reports.arn]
  }
}

resource "aws_iam_role_policy" "audit_inline" {
  name   = "${var.name_prefix}-inline"
  role   = aws_iam_role.audit.id
  policy = data.aws_iam_policy_document.audit_inline.json
}
