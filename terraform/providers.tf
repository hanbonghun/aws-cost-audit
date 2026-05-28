provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "aws-cost-audit"
      ManagedBy = "Terraform"
      Owner     = "FinOps"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}
