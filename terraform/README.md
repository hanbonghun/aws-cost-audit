# Terraform — aws-cost-audit infrastructure

이 디렉토리는 aws-cost-audit가 사용하는 AWS 측 인프라를 정의합니다.

## 무엇이 생성되는가

| 리소스 | 목적 |
|---|---|
| `aws_s3_bucket.reports` | 매월 audit 리포트 저장 (versioning + 12개월 lifecycle) |
| `aws_iam_openid_connect_provider.github` | GitHub Actions OIDC 인증 |
| `aws_iam_role.audit` | ReadOnlyAccess + Billing + Compute Optimizer + Cost Explorer 읽기 권한 |
| `aws_sns_topic.reports` | 이메일/Slack 알림 발송 |
| `aws_budgets_budget.monthly` | 월 $5,000 임계값 알람 (옵션) |
| `aws_ce_anomaly_monitor.service` | 서비스별 이상 비용 감지 (옵션) |

## 배포 절차

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# tfvars 편집

terraform init
terraform plan
terraform apply
```

배포 후 outputs 에 출력되는 값을 GitHub repository secrets 에 등록합니다.

## 안전성

- IAM role 의 trust policy 는 **specific GitHub repo + branch** 만 허용 (다른 repo 가 hijack 불가)
- 권한은 **read-only** + 특정 S3 bucket write + 특정 SNS topic publish 로 제한
- 모든 자원에 `Project=aws-cost-audit`, `ManagedBy=Terraform` 태그 자동 부여

## State 관리

기본은 local state. 팀에서 사용하려면 별도 `backend.tf` 작성:

```hcl
terraform {
  backend "s3" {
    bucket         = "your-tf-state-bucket"
    key            = "aws-cost-audit/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "terraform-state-lock"
    encrypt        = true
  }
}
```

## OIDC provider가 이미 있는 경우

계정에 이미 `token.actions.githubusercontent.com` OIDC provider 가 있다면 import:

```bash
terraform import aws_iam_openid_connect_provider.github \
  arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com
```

이후 `terraform plan` 으로 diff 확인 후 `apply`.
