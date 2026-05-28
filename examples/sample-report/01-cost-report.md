# AWS 비용 리포트

Account 123456789012 · 2026-05-28T14:45:06Z  
권한: `arn:aws:iam::123456789012:role/aws-cost-audit-reader` (read-only)

## 요약

**월별 총비용** (Cost Explorer 실측):

| 기간 | 비용 |
|---|---:|
| 2026-02-27 → 2026-03-01 | $150.26 |
| 2026-03-01 → 2026-04-01 | $3,873.98 |
| 2026-04-01 → 2026-05-01 | $3,563.40 |
| 2026-05-01 → 2026-05-28 | $3,399.98 |

**서비스별 비용** (2026-04-01 기준):

| 순위 | 서비스 | 비용 | 비중 |
|---:|---|---:|---:|
| 1 | Amazon Elastic Compute Cloud - Compute | $1,479.89 | 41.5% |
| 2 | Amazon Virtual Private Cloud | $580.40 | 16.3% |
| 3 | Amazon Relational Database Service | $394.48 | 11.1% |
| 4 | Amazon Elastic Load Balancing | $372.88 | 10.5% |
| 5 | Tax | $323.96 | 9.1% |
| 6 | EC2 - Other | $268.80 | 7.5% |
| 7 | Amazon ElastiCache | $86.54 | 2.4% |
| 8 | AWS Secrets Manager | $21.51 | 0.6% |
| 9 | AWS WAF | $13.15 | 0.4% |
| 10 | AmazonCloudWatch | $8.39 | 0.2% |
| 11 | AWS Key Management Service | $8.00 | 0.2% |
| 12 | Amazon Simple Queue Service | $2.48 | 0.1% |

**주요 지표**

- EC2 25대 · idle (30일 avg CPU < 5%) 22대
- ALB 24개 · zero-traffic 5개 · low-traffic (<1k req/day) 13개
- NAT GW 4개 · zero-traffic 1개 · 고정비 합 $172/mo
- RDS 11개 · idle 1개
- ElastiCache 7개 · likely-idle 0개
- Savings Plans coverage 0.0%
- RI coverage 57.6%
- Compute SP 추천 적용 시 추가 절감 $232.2882838780/mo (28.1%)

**예상 절감 추정** (Phase 1–2):

| 액션 | 월 절감 | 위험 |
|---|---:|---|
| Compute SP 구매 ($0.738/hr) | $232.2882838780 | 없음 |
| Zero-traffic ALB 5개 정리 | $110+ | 낮음 (트래픽 재확인) |
| Zero-traffic NAT GW 1개 제거 | $42 | 중간 (라우팅 변경) |
| 미사용 스냅샷 6개 (250 GiB) 삭제 | $12 | 없음 |
| EBS gp2 → gp3 (5개) | $3 | 없음 |
| IDLE RDS 1개 종료 (final snapshot 후) | $22 | 낮음 (데이터 백업) |
| Compute Optimizer 추천 적용 (16 EC2 + 26 EBS) | $49 | 낮음 (추천별 risk 확인) |

## 1. Idle EC2 인스턴스

| Id | Type | Name | AvgCPU% | MaxCPU% | Net30d GiB | Verdict |
|---|---|---|---:|---:|---:|---|
| `i-00000000000000001` | t3.micro | shared-bastion-2 | 0.16 | 6.62 | 0.02 | KEEP-BASTION |
| `i-00000000000000002` | t4g.nano | stag-app-6 | 0.27 | 25.38 | 0.27 | REVIEW |
| `i-00000000000000003` | t3.small | shared-app-1 | 0.36 | 39.08 | 0.72 | REVIEW |
| `i-00000000000000004` | t4g.medium | shared-bi-2 | 0.55 | 2.00 | 2.21 | DOWNSIZE |
| `i-00000000000000005` | t3.large | prod-app-3 | 0.59 | 90.71 | 2.29 | REVIEW |
| `i-00000000000000006` | t3.small | stag-app-4 | 0.65 | 14.38 | 0.19 | DOWNSIZE |
| `i-00000000000000007` | t3.xlarge | prod-app-1 | 0.99 | 38.90 | 23.25 | REVIEW |
| `i-00000000000000008` | t3.medium | shared-app-8 | 1.00 | 71.43 | 6.17 | REVIEW |
| `i-00000000000000009` | t3.xlarge | stag-app-1 | 1.05 | 64.62 | 22.52 | REVIEW |
| `i-0000000000000000a` | t3.medium | dev-app-5 | 1.06 | 95.56 | 26.41 | REVIEW |
| `i-0000000000000000b` | t2.micro | shared-bastion-1 | 1.16 | 42.50 | 41.39 | KEEP-BASTION |
| `i-0000000000000000c` | t3.xlarge | prod-app-1 | 1.19 | 92.51 | 19.81 | REVIEW |
| `i-0000000000000000d` | t3.small | dev-app-6 | 1.22 | 56.20 | 0.83 | REVIEW |
| `i-0000000000000000e` | t3.xlarge | stag-app-1 | 1.23 | 95.54 | 25.44 | REVIEW |
| `i-0000000000000000f` | t3.large | dev-app-1 | 1.28 | 17.32 | 0.29 | DOWNSIZE |
| `i-00000000000000010` | t3.small | stag-app-4 | 1.55 | 79.07 | 1.04 | REVIEW |
| `i-00000000000000011` | t3.large | dev-ci-1 | 1.59 | 95.79 | 61.49 | REVIEW |
| `i-00000000000000012` | t3.xlarge | dev-app-2 | 1.71 | 68.72 | 66.13 | REVIEW |
| `i-00000000000000013` | t3.large | dev-obs-1 | 3.11 | 55.70 | 19.49 | REVIEW |
| `i-00000000000000014` | t2.medium | shared-app-2 | 3.22 | 40.63 | 0.43 | REVIEW |
| `i-00000000000000015` | t3.medium | stag-obs-1 | 3.32 | 56.58 | 24.16 | REVIEW |
| `i-00000000000000016` | r7i.2xlarge | shared-bi-1 | 3.59 | 25.06 | 5.35 | REVIEW |

## 2. Zero-traffic ALBs

| Region | Name | Listeners | Created |
|---|---|---:|---|
| ap-northeast-2 | shared-app-2-alb | - | 2025-10-05 |
| ap-northeast-2 | shared-app-5-alb | - | 2025-10-28 |
| ap-northeast-2 | prod-app-4-alb | - | 2025-11-06 |
| ap-northeast-2 | dev-app-5-alb | - | 2025-11-24 |
| ap-northeast-2 | prod-app-5-alb | - | 2025-12-22 |

## 3. NAT Gateway 사용도

| Id | VPC | 30d GiB | 평가 |
|---|---|---:|---|
| `nat-00000000000000001` | `vpc-00000000000000001` | 0.99 | VERY-LOW |
| `nat-00000000000000002` | `vpc-00000000000000002` | 0.68 | VERY-LOW |
| `nat-00000000000000003` | `vpc-00000000000000003` | 0.14 | VERY-LOW |
| `nat-00000000000000004` | `vpc-00000000000000004` | 0.0 | ZERO-TRAFFIC |

## 4. RDS Database

| Id | Class | Engine | MAZ | CPU% | Conn | Verdict |
|---|---|---|:-:|---:|---:|---|
| `shared-app-14` | db.t4g.micro | mysql |  | 3.23 | 0.0 | DOWNSIZE |
| `dev-app-1-postgres` | db.t4g.micro | postgres |  | 3.4 | 4.32 | DOWNSIZE |
| `dev-app-2-postgres` | db.t4g.micro | postgres |  | 4.19 | 9.9 | DOWNSIZE |
| `dev-app-3-postgres` | db.t4g.micro | postgres |  | 3.26 | 8.56 | DOWNSIZE |
| `shared-app-1-postgres` | db.t4g.micro | postgres |  | 3.35 | 0.23 | IDLE |
| `prod-app-1-postgres` | db.r6g.large | postgres | Y | 3.2 | 22.01 | OK |
| `prod-app-2-postgres` | db.t4g.medium | postgres |  | 4.5 | 9.82 | DOWNSIZE |
| `shared-app-2-postgres` | db.t4g.micro | postgres |  | 3.4 | 10.11 | DOWNSIZE |
| `stag-app-1-postgres` | db.t4g.micro | postgres |  | 4.33 | 10.35 | DOWNSIZE |
| `stag-app-2-postgres` | db.t4g.micro | postgres |  | 3.22 | 20.12 | DOWNSIZE |
| `stag-app-3-postgres` | db.t4g.small | postgres |  | 3.65 | 19.8 | DOWNSIZE |

## 5. ElastiCache

| Id | Type | CPU% | Conn | Mem% | Verdict |
|---|---|---:|---:|---:|---|
| `dev-app-1-cache-001` | cache.t3.small | 2.05 | 30.8 | 0.74 | OK |
| `dev-app-2-cache-001` | cache.t4g.micro | 2.28 | 5.5 | 1.7 | OK |
| `prod-app-1-cache-001` | cache.t3.small | 2.09 | 56.6 | 0.76 | OK |
| `shared-app-1-cache-001` | cache.t3.small | 2.25 | 5.5 | 1.07 | OK |
| `stag-app-1-cache-001` | cache.t4g.micro | 2.43 | 5.5 | 2.65 | OK |
| `stag-app-2-cache-001` | cache.t3.small | 2.16 | 56.8 | 0.75 | OK |
| `stag-app-3-cache-001` | cache.t4g.micro | 2.34 | 6.3 | 1.7 | OK |

## 6. 미사용 스냅샷 (AMI 종속성 체크 완료)

- AMI 종속 (보관 필요): 8개
- 독립 (안전 삭제 가능): **6개 (250 GiB)**

| SnapshotId | Size GiB | Started |
|---|---:|---|
| `snap-00000000000000001` | 30 | 2026-02-12 |
| `snap-00000000000000002` | 30 | 2026-02-12 |
| `snap-00000000000000003` | 30 | 2026-02-12 |
| `snap-00000000000000004` | 30 | 2026-02-12 |
| `snap-00000000000000005` | 30 | 2025-10-16 |
| `snap-00000000000000006` | 100 | 2025-04-18 |

## 7. Compute Optimizer 추천

- EC2 rightsizing: 16건 (~$46/mo 절감 가능)
- EBS rightsizing: 26건 (~$3/mo)
- Lambda rightsizing: 1건 (~$0/mo)
- ASG rightsizing: 0건

## 8. 거버넌스 (태그)

| 리소스 타입 | 총 | 누락(any) | NoOwner | NoProject | NoEnv |
|---|---:|---:|---:|---:|---:|
| ec2:instance | 26 | 23 | 23 | 15 | 15 |
| ec2:volume | 9 | 4 | 3 | 3 | 4 |
| elasticache:cluster | 7 | 5 | 5 | 0 | 0 |
| elasticloadbalancing:loadbalancer | 10 | 8 | 7 | 2 | 3 |
| rds:db | 9 | 7 | 7 | 2 | 2 |

## 9. 부속 산출물

- `02-problems.md` — 발견 문제 (심각도별)
- `03-improvements.md` — Phase 1/2/3 액션 플랜
- `99-methodology.md` — 데이터 출처와 한계
- `data/` — 카테고리별 raw CSV