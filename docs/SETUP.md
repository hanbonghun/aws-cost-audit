# Setup Guide

처음부터 끝까지 따라하면 동작하는 상태가 됩니다. 약 30분.

## 사전 준비

- AWS 계정 (관리자 권한 필요 — Terraform apply 시점에만)
- GitHub repository (이 코드를 push할 곳)
- Terraform 1.5+ 설치 (`brew install terraform`)
- AWS CLI 설치 (`brew install awscli`)

## 1. Repo 셋업 (이 repo가 이미 만들어져 있다면 skip)

```bash
git clone git@github.com:your-org/aws-cost-audit.git
cd aws-cost-audit
```

## 2. Terraform 변수 설정

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

`terraform.tfvars` 편집:

```hcl
github_org    = "your-org"
github_repo   = "aws-cost-audit"
github_branch = "main"

notification_emails = [
  "you@example.com",
]

region                        = "ap-northeast-2"
enable_budget_alarm           = true
monthly_budget_usd            = 5000
enable_cost_anomaly_detection = true
```

## 3. AWS 자격증명 — 관리자 (1회만)

Terraform apply 시에만 관리자 권한이 필요합니다. 그 외에는 readonly만 사용.

```bash
aws configure --profile admin
# 또는 aws-vault, AWS SSO 사용
export AWS_PROFILE=admin
aws sts get-caller-identity  # 관리자 ARN 확인
```

## 4. Terraform apply

```bash
terraform init
terraform plan
# 검토 후
terraform apply
```

성공 시 outputs 출력:

```
iam_role_arn      = "arn:aws:iam::123456789012:role/aws-cost-audit-reader"
s3_bucket_name    = "aws-cost-audit-reports-123456789012"
sns_topic_arn     = "arn:aws:sns:ap-northeast-2:123456789012:aws-cost-audit-reports"
```

> ⚠️ OIDC provider가 이미 계정에 있다면 import 필요:
> ```
> terraform import aws_iam_openid_connect_provider.github \
>   arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com
> ```

## 5. GitHub Secrets 등록

GitHub repo → Settings → Secrets and variables → Actions → New repository secret

| Secret | 값 |
|---|---|
| `AWS_ROLE_ARN` | Terraform output `iam_role_arn` |
| `S3_REPORT_BUCKET` | Terraform output `s3_bucket_name` |
| `SNS_TOPIC_ARN` | Terraform output `sns_topic_arn` |
| `AWS_REGION` | `ap-northeast-2` |
| `SLACK_WEBHOOK_URL` | (옵션) Slack incoming webhook URL |

Slack webhook 생성 방법: https://api.slack.com/messaging/webhooks

## 6. SNS 이메일 구독 승인

`terraform apply` 직후 입력한 이메일로 AWS SNS 구독 확인 메일이 옵니다. 링크 클릭하여 승인.

## 7. 첫 실행 (수동)

GitHub repo → Actions → "On-Demand Audit" → Run workflow

성공하면:
- S3 bucket 에 `YYYY-MM-DD/` 경로로 리포트 파일들 업로드
- 등록된 이메일로 SNS 요약 발송
- Slack 채널에 요약 게시 (설정한 경우)

## 8. 정기 실행 확인

매월 1일 09:00 KST (00:00 UTC)에 자동 실행됩니다.

GitHub Actions 탭에서 schedule 확인:
```
Actions → Monthly Cost Audit → 다음 실행 예정 시간 표시
```

## 일반적인 문제

### "Could not assume role" 에러
- IAM role의 trust policy가 정확한 repo:ref를 허용하는지 확인
- `terraform.tfvars` 의 `github_branch` 가 `main` 인지 (아니면 `*` 로 변경)

### "AccessDenied" on Cost Explorer
- AWS Account Settings에서 IAM user access to Billing 이 활성화되어 있는지 확인
- 또는 `arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess` 가 role에 attached 되어 있는지 (Terraform 이미 처리)

### Lambda timeout (이 도구는 GitHub Actions라 해당 없음)
- 30분 timeout. 그래도 초과하면 일부 investigation 비활성화

## 로컬에서 실행 (디버깅용)

```bash
cd scripts
pip install -r requirements.txt

# AWS 자격증명 (readonly 권장)
export AWS_PROFILE=analysis-readonly
export AWS_REGION=ap-northeast-2

# 로컬 출력만 (업로드 안 함)
unset S3_REPORT_BUCKET SNS_TOPIC_ARN SLACK_WEBHOOK_URL
python audit.py

# 출력 확인
ls audit-output/$(date +%Y-%m-%d)/
```
