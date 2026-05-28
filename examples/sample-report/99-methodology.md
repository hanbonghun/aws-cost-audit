# 방법론과 한계

2026-05-28T14:45:06Z

## 데이터 출처

- EC2/EBS/Snapshot/NAT/ALB: `ec2:Describe*`, `elasticloadbalancing:Describe*`
- 메트릭: CloudWatch `GetMetricStatistics` (30일, period=86400)
- 비용 추이: Cost Explorer `GetCostAndUsage`
- 추천: Compute Optimizer `Get*Recommendations`, Cost Explorer `Get*PurchaseRecommendation`
- 태그 감사: ResourceGroupsTaggingAPI `GetResources`

## 가격 기준

AWS 공시 On-Demand 가격 (ap-northeast-2), 2026년 초 기준. RI/SP 적용 후 실제 비용은 더 낮음.
정확한 비용은 Cost Explorer 의 UnblendedCost 참조.

## 한계

1. 인스턴스 내부 프로세스/cron 은 별도 SSM Inventory 필요
2. S3 객체 access pattern 은 Storage Lens 필요
3. Trusted Advisor cost 체크는 Business+ support plan 필요
4. 단일 시점 스냅샷 — 분석 직후 새 리소스 반영 안 됨

## 검증 로그

- 호출 신원: `arn:aws:iam::123456789012:role/aws-cost-audit-reader`
- 사용된 API 동사: `describe-*`, `list-*`, `get-*` 만
- CloudTrail 에서 `*Create*`, `*Modify*`, `*Delete*` 이벤트 0 검증 가능