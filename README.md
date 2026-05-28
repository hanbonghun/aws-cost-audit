# aws-cost-audit

Monthly AWS cost audit, run as a GitHub Actions cron. OIDC-only authentication. ~$0.30/month operational cost. No agents, no SaaS, no long-lived keys.

The workflow assumes a read-only IAM role via OIDC, runs 17 investigations covering idle resources, rightsizing, cost trends, Savings Plans coverage, snapshot dependencies, and tag hygiene, then writes Markdown and CSV reports to S3 with a summary delivered via SNS and Slack. The role grants no write, modify, or delete permissions on audited resources — verifiable via CloudTrail.

> **Privacy note**: reports contain resource IDs, ARNs, tag values, and account numbers. Keep the report S3 bucket private (the bundled Terraform does this by default) and never commit the local `audit-output/` directory.

## Quick start

Two ways to start, depending on your goal.

### Track A — Try it locally (5 minutes, no AWS resources created)

Just want to see what the report looks like for your account? Run the script against your existing read-only AWS profile. Nothing is created in your account — reports land in `./audit-output/`.

Prerequisites: Python 3.11+, AWS credentials with read access (see [Required permissions](#required-permissions) below).

```bash
git clone https://github.com/your-org/aws-cost-audit.git
cd aws-cost-audit
python -m pip install -r scripts/requirements.txt

export AWS_PROFILE=your-readonly-profile   # or AWS_ACCESS_KEY_ID / SECRET / SESSION_TOKEN
export AWS_REGION=ap-northeast-2

python scripts/audit.py
```

Output lands in `./audit-output/YYYY-MM-DD/`. Open `01-cost-report.md` first.

Missing permissions degrade gracefully — API calls that fail with `AccessDenied` log a warning and the corresponding section of the report is empty.

### Track B — Production deployment (monthly cron, ~30 minutes)

For ongoing monthly automation: bundled Terraform creates an IAM role assumed by GitHub Actions via OIDC, an S3 bucket for report archival, an SNS topic for email summary, and (optional) Slack webhook delivery. ~$0.30/month operational cost.

Prerequisites: above + Terraform 1.5+ + AWS admin credentials for the one-time `terraform apply`.

```bash
git clone https://github.com/your-org/aws-cost-audit.git
cd aws-cost-audit/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: github_org, github_repo, notification_emails
terraform init && terraform apply
```

Register the three Terraform outputs as GitHub repository secrets:

| Terraform output | GitHub secret |
|---|---|
| `iam_role_arn` | `AWS_ROLE_ARN` |
| `s3_bucket_name` | `S3_REPORT_BUCKET` |
| `sns_topic_arn` | `SNS_TOPIC_ARN` |

Then trigger the first audit manually: **Actions → On-Demand Audit → Run workflow**. The report lands in S3 within ~10 minutes. The monthly cron takes over on the 1st of every month at 00:00 UTC.

For Slack webhook setup, OIDC provider import conflicts, and troubleshooting, see [`docs/SETUP.md`](docs/SETUP.md). For architecture details, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). For the IAM policy, the full list of AWS APIs called, and how to verify read-only safety yourself, see [`docs/SECURITY.md`](docs/SECURITY.md).

### Required permissions

For **Track A** (local run), attach these AWS-managed policies to the IAM user or role you authenticate as:

| Policy | Covers |
|---|---|
| `arn:aws:iam::aws:policy/ReadOnlyAccess` | EC2 / RDS / Lambda / S3 / Route 53 / CloudFront / CloudWatch metrics + logs / Auto Scaling / ELB |
| `arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess` | Cost Explorer monthly trend + service breakdown |
| `arn:aws:iam::aws:policy/ComputeOptimizerReadOnlyAccess` | EC2 / EBS / Lambda / ASG right-sizing recommendations |

You can run with only `ReadOnlyAccess` — the cost-trend and right-sizing sections will be empty but the rest of the report still works.

For **Track B** (production), the bundled Terraform attaches these for you, scoped to a single IAM role that only GitHub Actions in your specific repository can assume. You don't need to attach anything manually. See [`docs/SECURITY.md`](docs/SECURITY.md) for the full policy and the inline `ce:Get*` actions used.

## License

MIT. See [`LICENSE`](LICENSE).

---

## 한국어 안내

매월 1일 AWS 비용을 자동으로 분석하고, S3에 리포트를 저장하고 Slack/Email로 요약을 발송하는 GitOps 기반 비용 감사 시스템.

**Read-only** — AWS 리소스에 어떤 변경도 가하지 않습니다. 분석 결과를 보고할 뿐.

> **프라이버시 안내**: 리포트에는 리소스 ID, ARN, 태그 값, 계정 번호가 포함됩니다. 리포트용 S3 버킷은 private 으로 유지해 주세요 (Terraform 기본값). 로컬에 생성되는 `audit-output/` 디렉터리도 커밋하지 마세요.

### 무엇을 분석하는가

17개 카테고리에 걸친 비용 최적화 기회 자동 탐지:

| # | 카테고리 | 발견하는 것 |
|---:|---|---|
| 1 | Cost Explorer 추이 | 월별 총비용, 서비스별 Top 10 |
| 2 | Idle EC2 | 30일 평균 CPU < 5% 인스턴스 + 종료 카테고리 분류 |
| 3 | Zero-traffic ALB | 30일 RequestCount 0인 ALB |
| 4 | NAT Gateway 사용도 | BytesOut 기준 미사용 / 통합 후보 |
| 5 | RDS / Aurora | Idle DB (conn < 1), 다운사이즈 후보 |
| 6 | ElastiCache | CPU/메모리 사용률, 노드 다운사이즈 |
| 7 | EBS gp2 → gp3 | 마이그레이션 가능 볼륨 + 예상 절감 |
| 8 | Old Snapshots | 90일+ 스냅샷의 AMI 종속성 체크 |
| 9 | Lambda | 메모리 over-provision 추천 |
| 10 | CloudWatch Logs | 보존 기간 미설정, 큰 그룹 |
| 11 | S3 lifecycle | lifecycle/versioning 미설정 버킷 |
| 12 | CloudFront / Route53 | 비활성 distribution |
| 13 | Compute Optimizer | EC2/EBS/Lambda rightsizing 추천 |
| 14 | Cost Explorer | 월별 추이 + 이상 패턴 |
| 15 | Savings Plans / RI | 커버리지 + 구매 추천 |
| 16 | Tagging governance | Owner/Project/Environment 누락 비율 |
| 17 | Orphaned 자원 | ENI/SG/AMI/TG/ASG/stopped-EC2 |

### 아키텍처

```
GitHub Actions (cron: 매월 1일 00:00 UTC = 09:00 KST)
        │
        ▼ OIDC AssumeRole (키 없음, 임시 자격증명)
AWS IAM role: aws-cost-audit-reader
  └─ ReadOnlyAccess + Billing read + Compute Optimizer read
        │
        ▼ 17 investigations 병렬 실행
        │
        ├─▶ S3 bucket  (리포트 markdown + CSV, 12개월 보존)
        ├─▶ SNS topic  → Email 구독자에게 요약 발송
        └─▶ Slack webhook → 채널에 요약 + S3 링크 게시
```

**왜 GitHub Actions인가**: Lambda 15분 timeout 제약 없음, 기존 bash+python 스크립트 그대로 재사용, 디버깅 쉬움, 무료 (월 2000분 한도 내).

### 빠른 시작

목적에 따라 두 트랙 중 선택.

#### Track A — 로컬에서 한 번 돌려보기 (5분, AWS 리소스 생성 없음)

내 계정에서 어떤 리포트가 나오는지 평가만 해보고 싶다면, 본인의 read-only AWS profile 로 스크립트를 직접 실행합니다. 계정에 아무것도 만들어지지 않고 리포트는 `./audit-output/` 에 떨어집니다.

준비물: Python 3.11+, read 권한이 있는 AWS 자격증명 ([필요 권한](#필요-권한) 참고).

```bash
git clone https://github.com/your-org/aws-cost-audit.git
cd aws-cost-audit
python -m pip install -r scripts/requirements.txt

export AWS_PROFILE=your-readonly-profile   # 또는 AWS_ACCESS_KEY_ID / SECRET / SESSION_TOKEN
export AWS_REGION=ap-northeast-2

python scripts/audit.py
```

`./audit-output/YYYY-MM-DD/01-cost-report.md` 부터 확인. 일부 API 권한이 없으면 해당 섹션만 비어 있고 나머지는 정상 출력됩니다 (`AccessDenied` 는 warning 로그 후 skip).

#### Track B — 운영 자동화 (월 1회 cron, 약 30분)

매월 자동 실행 + S3 보관 + SNS/Slack 발송이 필요하다면 번들된 Terraform 으로 IAM role / S3 bucket / SNS topic 을 한 번에 만들고 GitHub Actions OIDC 로 연결합니다. 월 운영 비용 약 $0.30.

준비물: 위 + Terraform 1.5+ + Terraform apply 용 admin 자격증명 (1회만).

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars 편집 — github_org, github_repo, notification_emails 등
terraform init && terraform apply
```

생성되는 자원:
- S3 bucket: `aws-cost-audit-reports-{account_id}` (versioning, lifecycle 12개월)
- IAM OIDC provider for GitHub
- IAM role: `aws-cost-audit-reader` (특정 GitHub repo 만 assume 가능)
- SNS topic + email subscription
- (옵션) AWS Budgets monthly $5,000 알람
- (옵션) Cost Anomaly Detection monitor

Terraform output 값을 repo Settings → Secrets 에 등록:

| Secret | 값 |
|---|---|
| `AWS_ROLE_ARN` | Terraform output `iam_role_arn` |
| `S3_REPORT_BUCKET` | Terraform output `s3_bucket_name` |
| `SNS_TOPIC_ARN` | Terraform output `sns_topic_arn` |
| `SLACK_WEBHOOK_URL` | (옵션) Slack incoming webhook URL |

수동 실행: **Actions → On-Demand Audit → Run workflow**. 또는 매월 1일 09:00 KST 자동 실행 대기.

#### 필요 권한

**Track A** (로컬 실행) 의 경우, 인증에 쓰이는 IAM user / role 에 다음 managed policy 들을 attach:

| Policy | 커버 범위 |
|---|---|
| `arn:aws:iam::aws:policy/ReadOnlyAccess` | EC2 / RDS / Lambda / S3 / Route 53 / CloudFront / CloudWatch / ELB |
| `arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess` | Cost Explorer 월별 추이 + 서비스별 분해 |
| `arn:aws:iam::aws:policy/ComputeOptimizerReadOnlyAccess` | EC2 / EBS / Lambda / ASG rightsizing 추천 |

`ReadOnlyAccess` 만 있어도 동작합니다. Cost / rightsizing 섹션이 빈 채로 출력될 뿐.

**Track B** (운영) 는 Terraform 이 위 권한을 가진 IAM role 을 자동으로 만들고, 본인 GitHub repo 에서만 OIDC 로 assume 할 수 있게 trust policy 를 묶어줍니다. 별도 attach 불필요. 전체 권한 명세는 [`docs/SECURITY.md`](docs/SECURITY.md) 참고.

### 산출물

각 실행마다 S3에 다음 파일들이 업로드됩니다:

```
s3://aws-cost-audit-reports-{account}/
└── 2026-06-01/
    ├── 01-cost-report.md
    ├── 02-problems.md
    ├── 03-improvements.md
    ├── 99-methodology.md
    └── data/
        ├── ec2_idle.csv
        ├── alb_traffic.csv
        ├── ...
        └── master_summary.json
```

### 안전장치

이 도구는 **READ-ONLY** 입니다. 다음과 같이 강제됩니다:

1. IAM role 에 `*Create*`, `*Delete*`, `*Modify*`, `*Put*`, `*Update*` 등의 권한이 **없음** (ReadOnlyAccess만)
2. 스크립트 내부에서도 모든 호출은 `describe-*`, `list-*`, `get-*` 만 사용
3. CloudTrail 로 변경 이벤트 검증 가능

자세한 권한 명세 + 호출하는 AWS API 전체 목록 + CloudTrail 로 직접 검증하는 명령은 [`docs/SECURITY.md`](docs/SECURITY.md) 에 정리되어 있습니다. 아키텍처 다이어그램과 데이터 흐름은 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### 비용

거의 0:

| 항목 | 월 비용 |
|---|---:|
| GitHub Actions (~10분/월) | $0 (free tier) |
| Lambda | — (사용 안 함) |
| S3 (리포트 ~5MB × 12개월) | <$0.01 |
| SNS (이메일 발송 12회/년) | <$0.01 |
| Cost Explorer API 호출 | $0.01/호출 × ~10 = $0.10 |
| CloudWatch GetMetricData | <$0.20 |
| **합계** | **~$0.30/월** |

### 폴더 구조

```
.
├── README.md                      # 이 파일
├── LICENSE
├── .gitignore
├── scripts/
│   ├── audit.sh                   # GitHub Actions 진입점
│   └── lib/
│       ├── __init__.py
│       ├── collect.py              # 17개 investigation 수집
│       ├── analyze.py              # 분류/판정 로직
│       ├── report.py               # markdown/CSV 생성
│       └── notify.py               # S3/SNS/Slack 발송
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── providers.tf
│   ├── iam.tf                      # OIDC role + policies
│   ├── s3.tf                       # 리포트 저장소
│   ├── sns.tf                      # 알림 토픽
│   ├── budgets.tf                  # AWS Budgets (옵션)
│   ├── anomaly.tf                  # Cost Anomaly Detection (옵션)
│   └── terraform.tfvars.example
├── .github/
│   └── workflows/
│       ├── monthly-audit.yml       # 매월 1일 cron
│       ├── on-demand-audit.yml     # 수동 트리거
│       └── terraform.yml           # PR validation
└── docs/
    ├── ARCHITECTURE.md
    ├── SETUP.md
    └── ROADMAP.md
```

### 로드맵

- [x] 17개 investigation 수집기
- [x] Markdown + CSV 리포트 생성
- [x] Terraform 인프라 (IAM, S3, SNS)
- [x] GitHub Actions cron
- [ ] 월별 diff (이번 달 vs 지난 달 변화)
- [ ] GitHub Issue 자동 생성 (Phase 1 액션을 트래킹 가능한 형태로)
- [ ] CloudWatch Dashboard 자동 export
- [ ] Multi-account 지원 (AWS Organizations)
