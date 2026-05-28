# Roadmap

## v1.0 — Initial Release (현재)

- [x] 17개 investigation 수집기
  - EC2 idle (CPU + Network)
  - ALB zero-traffic
  - NAT Gateway 사용도
  - RDS / Aurora
  - ElastiCache
  - EBS gp2 → gp3
  - Old snapshots + AMI 종속성
  - Lambda + Compute Optimizer
  - CloudWatch Logs
  - S3 lifecycle / versioning
  - CloudFront / Route53
  - Cost Explorer / SP/RI
  - Tag governance
  - Orphans (ENI, stopped EC2, TG, ASG, LT)
- [x] Markdown + CSV 리포트
- [x] Terraform 인프라 (IAM OIDC, S3, SNS, Budgets, Anomaly Detection)
- [x] GitHub Actions cron + on-demand workflows

## v1.1 — UX 개선

- [ ] **월별 diff 리포트**: 이전 달 vs 이번 달 변화 (신규 idle, 해소된 idle, 신규 zero-traffic ALB 등)
- [ ] **HTML 리포트** 자동 변환 (Pandoc) — 브라우저에서 보기 좋게
- [ ] **Slack 알림 개선** — Block Kit 사용, 색상 + 액션 버튼

## v1.2 — Action Tracking

- [ ] **GitHub Issue 자동 생성** — Phase 1 액션 각각을 Issue로 (책임자 placeholder, 마감일 설정)
- [ ] **이전 Issue 자동 close** — 다음 달 audit 에서 자원이 사라졌으면 close

## v2.0 — Multi-account

- [ ] **AWS Organizations 지원** — Management 계정에서 member 계정 순회
- [ ] **Cross-account role 통합** — 각 member 계정에 동일한 reader role을 Terraform module로 배포
- [ ] **통합 리포트** — 모든 계정 합산 + 계정별 분리

## v2.1 — 분석 고도화

- [ ] **데이터 전송(Data Transfer) 비용** — Inter-AZ, Inter-Region, CloudFront 비용 분해
- [ ] **태그 기반 코스트 어트리뷰션** — Project/Team별 비용 자동 분배
- [ ] **이상 패턴 탐지** — 단순 임계값 대신 통계적 anomaly (z-score)

## v2.2 — 자동 실행 (Optional)

- [ ] **자동 정리 PR** — 명확히 안전한 자원(스냅샷, 빈 SG)에 대해 Terraform 정리 PR 자동 생성
- [ ] **승인 워크플로우** — PR 리뷰 후 머지 → Terraform apply

## v3.0 — Web Dashboard

- [ ] **QuickSight 또는 Grafana 대시보드** — 시계열 추이
- [ ] **CSV → Athena 쿼리** — ad-hoc 분석

## 기타 아이디어

- 다른 클라우드 지원 (GCP, Azure) — 별도 collector
- Terraform → Pulumi 변환
- 비용 어트리뷰션 (FOCUS spec)
- 슬랙 슬래시 명령 `/cost-audit run` 수동 트리거
