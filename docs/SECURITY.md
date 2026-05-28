# Security model

이 문서는 `aws-cost-audit` 가 감사 대상 AWS 계정에 대해 **read-only** 임을 코드 한 줄 한 줄 검증하지 않아도 신뢰할 수 있도록 정리한 것입니다. 위협 모델, 부여되는 IAM 권한, 실제로 호출되는 AWS API, 그리고 그 중 *예외적으로* 쓰기가 허용된 AWS write 두 경로 + AWS 가 아닌 외부 전송 한 경로를 명시합니다.

## 위협 모델

이 도구가 막아야 하는 것:

1. **감사 대상 리소스의 의도치 않은 변경** — bug, supply-chain 공격, 또는 악의적 PR 이 감사 로직 안에서 destructive API 를 호출하는 경우
2. **장기 자격증명 유출** — workflow 나 코드에 박힌 access key 가 노출되어 영구 권한이 새는 경우
3. **다른 GitHub repo 의 hijack** — 다른 repo 가 같은 IAM role 을 가로채 임시 자격증명을 받는 경우

대응 수단:

| 위협 | 대응 |
|---|---|
| 감사 로직의 destructive API 호출 | IAM role 에서 write/modify/delete 권한 자체를 부여하지 않음 (아래 표 참조) |
| 장기 자격증명 유출 | OIDC 임시 자격증명만 사용. AWS access key 가 어디에도 존재하지 않음 |
| Cross-repo hijack | OIDC trust policy 가 `repo:<org>/<repo>:ref:refs/heads/<branch>` 로 한정 |

### 범위 밖 (이 도구만으로 막을 수 없는 위협)

- 이미 AWS 계정에 권한이 있는 내부자의 악의적 행위
- 리포트 S3 버킷이 별도로 노출되어 리소스 ID / ARN / 비용 수치가 유출되는 경우 (버킷은 Terraform 기본값으로 모든 public access 가 차단되지만, 후속 변경은 사용자 책임)
- `boto3` / `botocore` 등 transitive dependency 의 supply-chain 침해
- 본 repo 의 workflow 나 IAM trust policy 를 수정할 권한이 있는 GitHub org admin 의 악의적 변경

이 도구의 보장은 "감사 로직 자체가 destructive AWS API 를 호출하지 않는다" 까지입니다.

## 인증 — OIDC, 키 없음

GitHub Actions 가 발급한 JWT 를 AWS STS 가 검증 → 1시간 만료 임시 자격증명. Trust policy 의 `sub` 조건이 특정 repo 와 branch 만 허용 (`terraform/iam.tf:33-37`):

```
repo:<github_org>/<github_repo>:ref:refs/heads/<github_branch>
```

`github_branch = "*"` 로 설정 시에만 모든 branch 허용으로 풀립니다. 이 외 경우 — 다른 GitHub org / repo / branch 에서 같은 role 을 assume 시도 → STS 가 거부.

저장소나 GitHub Actions 어디에도 **장기 AWS access key 가 존재하지 않습니다**. OIDC token → STS → 임시 credential 경로 외 인증 수단을 추가하면 그것은 보안 회귀 (regression) 입니다.

## IAM 권한

`aws-cost-audit-reader` role 에 부착되는 정책:

### Managed policies (read-only)

| Policy ARN | 용도 |
|---|---|
| `arn:aws:iam::aws:policy/ReadOnlyAccess` | EC2 / RDS / Lambda / S3 / Route53 / CloudFront / CloudWatch / Logs / Auto Scaling / ELB 등의 `Describe*`, `List*`, `Get*` |
| `arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess` | Billing console + Cost Explorer 읽기 |
| `arn:aws:iam::aws:policy/ComputeOptimizerReadOnlyAccess` | Compute Optimizer 추천 조회 |
| `arn:aws:iam::aws:policy/CostOptimizationHubReadOnlyAccess` | Cost Optimization Hub (선택적) |
| `arn:aws:iam::aws:policy/AWSTrustedAdvisorPriorityReadOnlyAccess` | Trusted Advisor priority (Business+ support 필요) |

위 다섯 개는 AWS 가 관리하는 read-only managed policy 입니다. 현재 정의는 AWS Console 또는 `aws iam get-policy-version` 으로 검증 가능. `*Create*`, `*Delete*`, `*Modify*`, `*Put*`, `*Update*` action 이 포함되어 있지 않습니다. AWS 가 향후 read action 을 추가할 수는 있지만, write action 이 추가되면 그 정책 자체의 의미가 바뀌게 됩니다 — 변경 사항은 AWS 가 공지합니다.

> **이름 규칙**: 위 ARN 들은 `var.name_prefix` 기본값 (`aws-cost-audit`) 기준입니다. `terraform.tfvars` 에서 prefix 를 바꾸면 role / 버킷 / 토픽 이름도 따라 바뀝니다.

### Inline policy — 3개의 명시적 statement

`terraform/iam.tf:80-124` 의 inline policy document 는 정확히 세 statement 로 구성됩니다 (resource 선언은 `iam.tf:126-130`).

#### 1. `CostExplorerExplicit` (read)

`ce:*` 중 다음만:

```
ce:GetCostAndUsage              ce:GetCostForecast
ce:GetReservationCoverage       ce:GetReservationUtilization
ce:GetSavingsPlansCoverage      ce:GetSavingsPlansUtilization
ce:GetSavingsPlansPurchaseRecommendation
ce:GetReservationPurchaseRecommendation
ce:GetAnomalies                 ce:GetCostCategories
ce:ListCostCategoryDefinitions  ce:GetDimensionValues
```

모두 `Get*` 또는 `List*`. `ce:CreateAnomalyMonitor`, `ce:UpdateAnomalyMonitor` 같은 write action 은 부여되지 않습니다.

#### 2. `ReportBucketWrite` — 첫 번째 write 예외

```
Actions:    s3:PutObject, s3:PutObjectAcl, s3:GetObject, s3:ListBucket
Resources:  arn:aws:s3:::aws-cost-audit-reports-<account>
            arn:aws:s3:::aws-cost-audit-reports-<account>/*
```

`s3:PutObject` 는 리포트를 업로드하기 위한 유일한 write 권한이며, **이 도구가 Terraform 으로 직접 만든 단일 리포트 버킷 ARN** 으로 resource-scope 됩니다. 다른 어떤 버킷에도 쓸 수 없습니다.

#### 3. `SNSPublishReports` — 두 번째 write 예외

```
Actions:    sns:Publish
Resources:  arn:aws:sns:<region>:<account>:aws-cost-audit-reports
```

`sns:Publish` 는 요약 알림을 발송하는 유일한 write 권한이며, **이 도구가 Terraform 으로 직접 만든 단일 SNS topic ARN** 으로 resource-scope 됩니다. 토픽 생성 / 삭제 / 정책 변경 권한은 없습니다.

## 실제 호출하는 AWS API

`scripts/lib/collect.py` 와 `scripts/lib/notify.py` 가 호출하는 boto3 메서드 전체 목록입니다. 모든 read 는 `Describe*` / `List*` / `Get*` 동사로 시작합니다.

### 데이터 수집 (read-only, `collect.py`)

| AWS 서비스 | 메서드 | 용도 |
|---|---|---|
| STS | `get_caller_identity` | 실행 신원 기록 |
| EC2 | `describe_regions` | opted-in 리전 enumeration |
| EC2 | `describe_instances` | 실행 중 / 정지된 인스턴스 목록 |
| EC2 | `describe_volumes` | EBS 볼륨 inventory + unattached 검색 |
| EC2 | `describe_snapshots` (OwnerIds=self) | 90일+ 스냅샷 + AMI 종속성 |
| EC2 | `describe_addresses` | unattached EIP |
| EC2 | `describe_nat_gateways` | NAT Gateway inventory |
| EC2 | `describe_vpc_endpoints` | VPC endpoint inventory |
| EC2 | `describe_images` (Owners=self) | 자체 AMI 와 backing snapshot |
| EC2 | `describe_network_interfaces` | detached ENI |
| EC2 | `describe_launch_templates` | launch template inventory |
| ELBv2 | `describe_load_balancers`, `describe_target_groups` | ALB / NLB + orphan TG |
| ELB Classic | `describe_load_balancers` | classic LB |
| RDS | `describe_db_instances` | RDS 인스턴스 |
| ElastiCache | `describe_cache_clusters` | cache 노드 |
| Lambda | `list_functions` | Lambda 함수 inventory |
| CloudWatch | `get_metric_statistics` | 30일 CPU / 네트워크 / RequestCount / 메모리 등 |
| CloudWatch Logs | `describe_log_groups` | log group + retention |
| S3 | `list_buckets`, `get_bucket_location`, `get_bucket_lifecycle_configuration`, `get_bucket_versioning` | 버킷 inventory + lifecycle / versioning 점검 |
| CloudFront | `list_distributions` | distribution 활성 여부 |
| Route 53 | `list_hosted_zones` | 호스팅 영역 |
| Compute Optimizer | `get_enrollment_status`, `get_ec2_instance_recommendations`, `get_ebs_volume_recommendations`, `get_lambda_function_recommendations`, `get_auto_scaling_group_recommendations` | 권장 사이즈 |
| Cost Explorer | `get_cost_and_usage`, `get_savings_plans_coverage`, `get_reservation_coverage`, `get_savings_plans_purchase_recommendation` | 비용 추이 + SP / RI |
| Auto Scaling | `describe_auto_scaling_groups` | 0-capacity ASG |
| Resource Groups Tagging | `get_resources` | 태그 거버넌스 |

위 메서드는 전부 정보 조회입니다. write action 이 없습니다.

### 외부 전달 (write 예외, `notify.py`)

| 위치 | API | 무엇을 쓰는가 |
|---|---|---|
| `notify.py:33` `s3.upload_file` | `s3:PutObject` | 리포트 파일을 **자체 생성한** 리포트 버킷에 업로드 |
| `notify.py:44` `sns.publish` | `sns:Publish` | 요약을 **자체 생성한** SNS topic 에 publish |
| `notify.py:57` `urlopen(Slack webhook)` | (AWS 아님) HTTPS POST | Slack incoming webhook 으로 요약 전송. AWS API 가 아님 |

이 세 가지 외에 외부에 데이터가 나가는 경로는 없습니다.

## CloudTrail 로 직접 검증

이 도구가 정말 read-only 인지 본인의 CloudTrail 로 확인할 수 있습니다.

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=Username,AttributeValue=aws-cost-audit-reader \
  --start-time $(date -u -d '7 days ago' '+%Y-%m-%dT%H:%M:%SZ') \
  --query 'Events[?contains(EventName, `Create`) || contains(EventName, `Delete`) || contains(EventName, `Modify`) || contains(EventName, `Update`) || (contains(EventName, `Put`) && !contains(EventName, `PutObject`))]'
```

기대 결과: 빈 배열 `[]`.

`PutObject` 만 제외한 이유는 위 표의 `ReportBucketWrite` 예외 때문입니다. 다른 `Put*` (예: `PutBucketPolicy`) 가 나오면 위반입니다.

명령 사용 시 주의:
- `lookup-events` 는 **리전 단위**. 감사가 도는 모든 리전에서 각각 실행하거나, organization trail 의 CloudTrail Lake / S3 로그를 Athena 로 쿼리하세요.
- `lookup-events` 의 기본 보존 기간은 **90일**. 더 긴 기간은 CloudTrail Lake / S3 delivered events 가 필요합니다.
- 위 명령의 `date -u -d '7 days ago'` 는 GNU date 문법입니다. macOS 는 `date -u -v-7d '+%Y-%m-%dT%H:%M:%SZ'` 를 사용하세요.

## 감사용 체크리스트

저장소를 fork / clone 한 사용자가 직접 확인할 수 있는 항목:

1. `terraform/iam.tf` 의 inline policy 가 위 표의 3 statement (CostExplorerExplicit, ReportBucketWrite, SNSPublishReports) 와 일치하는가?
2. `terraform plan` 출력에 `aws_iam_role_policy_attachment` 가 다섯 개 (모두 read-only managed policy ARN) 인가?
3. `scripts/lib/collect.py` 에서 `boto3` 호출이 `describe_*` / `list_*` / `get_*` 패턴만 사용하는가? (`grep -E "\.client\(" scripts/lib/collect.py` 후 메서드명 확인)
4. `scripts/lib/notify.py` 외에 `s3:put`, `sns:publish`, `slack` 같은 write 경로가 추가된 곳이 없는가? (`grep -rE "(upload_file|put_object|publish|webhook)" scripts/`)
5. CloudTrail 로 위 명령 실행 결과가 빈 배열인가?

## 새로운 investigation 을 추가할 때

`AGENTS.md` 의 Non-Negotiable Safety Rules 와 결합해서 읽으세요. 핵심 규칙:

- 새 호출은 `describe_*` / `list_*` / `get_*` 패턴만 사용
- 새 권한이 필요하면 `terraform/iam.tf` 의 managed policy 만으로 충분한지 먼저 확인. 부족하면 inline statement 추가 시 **resource-scope** 필수.
- 외부 데이터 전송이 필요하면 `notify.py` 안에서, 그리고 위 세 가지 외 다른 write 가 발생하지 않는지 PR review 에서 명시.
