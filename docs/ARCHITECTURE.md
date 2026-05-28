# Architecture

## 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                       GitHub                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  GitHub Actions                                          │    │
│  │  • monthly-audit.yml (cron: 매월 1일)                    │    │
│  │  • on-demand-audit.yml (manual)                          │    │
│  │  • terraform.yml (PR validation)                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│         │                                                        │
│         │ OIDC token (JWT)                                       │
└─────────┼────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                        AWS (managed by Terraform)                │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ IAM OIDC Provider (token.actions.githubusercontent.com)  │  │
│  │   └─ Trust policy:                                       │  │
│  │      repo:your-org/aws-cost-audit:ref:refs/heads/main    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                       │
│                          ▼ AssumeRoleWithWebIdentity             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ IAM Role: aws-cost-audit-reader                          │  │
│  │   • ReadOnlyAccess                                       │  │
│  │   • AWSBillingReadOnlyAccess                             │  │
│  │   • ComputeOptimizerReadOnlyAccess                       │  │
│  │   • Inline: ce:*, sns:Publish, s3:Put (bucket-scoped)    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                       │
│                          ▼  17 investigations (parallel)         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Multi-region scan (boto3 ThreadPoolExecutor)             │  │
│  │   • ec2.describe_instances/volumes/snapshots/...         │  │
│  │   • elbv2.describe_*                                     │  │
│  │   • cloudwatch.get_metric_statistics                     │  │
│  │   • rds.describe_db_instances                            │  │
│  │   • lambda.list_functions                                │  │
│  │   • ce.get_cost_and_usage  (us-east-1)                   │  │
│  │   • compute-optimizer.get_*_recommendations              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                       │
│                          ▼ Output                                │
│  ┌──────────────────────┐  ┌─────────────────────────────────┐ │
│  │ S3 bucket            │  │ SNS topic                       │ │
│  │ aws-cost-audit-      │  │ aws-cost-audit-reports          │ │
│  │   reports-{account}  │  │   └─ Email subscribers          │ │
│  │   └─ 2026-06-01/     │  └─────────────────────────────────┘ │
│  │      ├─ *.md         │  ┌─────────────────────────────────┐ │
│  │      └─ data/*.csv   │  │ Slack webhook (optional)        │ │
│  │   Lifecycle: 12mo    │  └─────────────────────────────────┘ │
│  └──────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘
```

## 보안 모델

### 키 없는 인증 (OIDC)
- GitHub Actions가 발급한 JWT를 AWS STS에 제출 → 임시 자격증명 발급
- 장기 IAM access key 불필요 → 키 유출 위험 없음
- Trust policy 가 **특정 repo + branch** 만 허용

### 최소 권한 원칙
- ReadOnlyAccess + Billing + Compute Optimizer 의 read 권한만
- S3 write 는 **특정 bucket 만** (`aws_s3_bucket.reports.arn`)
- SNS publish 는 **특정 topic 만**
- 어떤 작성/수정/삭제 권한도 없음

### CloudTrail 검증 가능
이 도구가 호출하는 모든 API는 다음 동사로 시작:
- `Describe*`, `List*`, `Get*`, `Lookup*`, `Search*`

검증 명령:
```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=Username,AttributeValue=aws-cost-audit-reader \
  --start-time $(date -v-1d -u +%Y-%m-%dT%H:%M:%SZ) \
  --query 'Events[?contains(EventName, `Create`) || contains(EventName, `Delete`) || contains(EventName, `Modify`)]'
```
→ 결과가 빈 배열이어야 정상.

## 데이터 흐름

1. **GitHub Actions 시작** (cron 또는 manual)
2. **OIDC AssumeRole** — IAM role 의 임시 자격증명 (1시간 만료)
3. **17개 investigation 병렬 실행** — boto3 ThreadPoolExecutor (max_workers=20)
4. **분석/분류** — Idle EC2 verdict, RDS verdict, ALB category 등
5. **리포트 생성** — markdown (4개) + CSV (11개) + master_summary.json
6. **S3 업로드** — `s3://{bucket}/{YYYY-MM-DD}/`
7. **SNS publish** — 요약 텍스트
8. **Slack post** — 요약 + S3 링크 (옵션)

## 비용 모델

월간 1회 실행 기준:

| 항목 | 단가 | 사용량 | 월 비용 |
|---|---|---|---:|
| GitHub Actions 분 (private) | $0.008/분 | ~10분 | $0.08 (free tier 내) |
| Lambda | — | 사용 안 함 | $0 |
| Cost Explorer API | $0.01/req | ~10 req | $0.10 |
| CloudWatch GetMetricData | $0.01/1000 req | ~500 req | $0.005 |
| S3 storage | $0.025/GB | ~5 MB | < $0.001 |
| S3 PUT | $0.005/1000 | ~15 PUT | < $0.001 |
| SNS publish (email) | $0.50/1M (free 1k/mo) | ~5 emails | $0 |
| **합계** | | | **~$0.20/월** |

## 확장 포인트

### 추가 investigation
`scripts/lib/collect.py` 에 함수 추가:
```python
def collect_my_thing(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        client = session(region).client("...")
        ...
    return _parallel_regions(per_region, regions)
```
그 후 `scripts/audit.py` 의 main() 에서 호출.

### 추가 알림 채널
`scripts/lib/notify.py` 에 함수 추가 (e.g. `post_to_teams()`, `post_to_discord()`).

### 월별 diff
이전 달 S3 객체 (`s3://bucket/2026-05-01/data/master_summary.json`) 와 이번 달을 비교하여 신규 idle 자원만 보고하는 기능.

### Multi-account
AWS Organizations 의 모든 member 계정 순회. cross-account role assume 패턴 사용.
