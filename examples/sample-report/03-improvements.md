# 개선안 — Phase 1 / 2 / 3

2026-05-28T14:45:06Z

각 액션은 예상 절감, 위험, 사전 검증, 롤백 방법을 포함한다.

## Phase 1 — 즉시 실행 (위험 낮음)

### 1. Compute Savings Plan $0.738/hr 구매
- 절감: $232.2882838780/mo · $458/yr · 28% off
- 위험: 없음 (RI 만료 시 자동 흡수)
- 검증: 최근 60일 EC2 사용 안정성 확인 → AWS Console > Savings Plans
- 롤백: 1년 약정. ROI 가 높아 손익분기는 빠름.

### 2. 미사용 스냅샷 6개 삭제
- 절감: $12/mo
- 위험: 없음 (AMI 종속성 사전 확인 완료)
- 대상: `snap-00000000000000001`, `snap-00000000000000002`, `snap-00000000000000003`, `snap-00000000000000004`, `snap-00000000000000005` 외 1개
- 롤백: 삭제 후 복구 불가. EBS 원본은 남아 있음.

### 3. EBS gp2 → gp3 마이그레이션 (5개 / 150 GiB)
- 절감: $3/mo
- 위험: 없음 (in-place 변환, 다운타임 없음)
- 검증: gp3 기본 IOPS 3000 ≥ gp2 baseline
- 롤백: gp3 → gp2 재변환 가능

### 4. Zero-traffic ALB 5개 정리
- 절감: 약 $110/mo
- 위험: 낮음 (잠시 미사용일 가능성)
- 검증: Slack 공지 + Route53 record 확인
- 대상: `shared-app-2-alb`, `shared-app-5-alb`, `prod-app-4-alb`, `dev-app-5-alb`, `prod-app-5-alb`

## Phase 2 — 1–2주 (소유자 확인 필요, 위험 중간)

### 1. NAT Gateway 1개 제거 (zero traffic)
- 절감: $42/mo
- 위험: 중간 (라우팅 변경, VPC outbound 일시 중단 가능)
- 검증: VPC 라우팅 테이블 + Subnet usage 확인
- 대상: `nat-00000000000000004`
- 롤백: NAT GW 는 5분 내 재생성

### 2. IDLE RDS 1개 종료
- 절감: $22/mo
- 위험: 낮음 (final snapshot 으로 데이터 보존)
- 검증: Final snapshot 생성 → Performance Insights 로 최근 query 확인
- 대상: `shared-app-1-postgres`
- 롤백: snapshot 에서 복원

### 3. EC2 다운사이즈 3대
- 위험: 중간 (트래픽 스파이크 대응 검증 필요)
- 검증: max CPU < 20% 확인
- 롤백: 더 큰 사이즈로 재변경

### 4. Compute Optimizer 추천 적용 (EC2 16건 + EBS 26건)
- 절감: 약 $49/mo
- 위험: 낮음 (추천별 'Risk' 컬럼 확인 — Very Low → Low → Medium 순서로 적용)

## Phase 3 — 전략 (1개월+)

### 1. ECS 클러스터 통합 또는 Fargate 전환
- 절감: $200–500/mo (예상)
- 검증: 각 클러스터의 desired/running count, capacity provider 활용도
- 롤백: 별도 클러스터로 분리 가능

### 2. Tag enforcement (SCP)
- Service Control Policy 로 Owner/Project/Environment 강제
- staging 환경에서 먼저 검증

### 3. Cost Anomaly Detection + AWS Budgets (Terraform 에 이미 포함)
- 월 $5,000 임계값
