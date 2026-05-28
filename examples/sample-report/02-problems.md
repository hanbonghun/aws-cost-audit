# 발견된 문제

2026-05-28T14:45:06Z

### [HIGH] Savings Plans 커버리지 0%

- 위치: Account 전역
- 월비용 영향: 약 $232
- 설명: Compute SP 구매 시 $232.288283878/mo 절감 가능. ROI 43%.

### [HIGH] NAT Gateway 1개가 30일 트래픽 0

- 위치: ap-northeast-2
- 월비용 영향: 약 $42
- 설명: 시간당 고정비만 청구 중. 라우팅 테이블 검토 후 제거.

### [MED] ALB 5개 zero-traffic

- 위치: 전 리전
- 월비용 영향: 약 $110
- 설명: 사용처가 정말 없는지 확인 후 삭제.

### [MED] RDS IDLE 1개 (avg conn < 1)

- 위치: 전 리전
- 월비용 영향: 약 $22
- 설명: 종료 대상: `shared-app-1-postgres`

### [MED] Idle EC2 22대 (avg CPU < 5%)

- 위치: 전 리전
- 설명: 각 인스턴스의 Verdict 별 액션 (TERMINATE / DOWNSIZE / KEEP) 검토.

### [MED] EC2 23/26 (88%) Owner/Project/Env 태그 누락

- 위치: 전역
- 설명: 정리 작업 시 책임자 추적 불가. Tag enforcement (SCP) 도입 권장.

### [LOW] Compute Optimizer 추천 42건 미적용

- 위치: ap-northeast-2
- 월비용 영향: 약 $49
- 설명: AWS 자체 추천. Console 의 'Very Low' risk 부터 적용.

### [LOW] AMI 미종속 90일+ 스냅샷 6개 (250 GiB)

- 위치: ap-northeast-2
- 월비용 영향: 약 $12
- 설명: AMI 종속성 확인 완료. 안전하게 삭제 가능.

### [LOW] EBS gp2 볼륨 5개 (150 GiB) → gp3 가능

- 위치: 전 리전
- 월비용 영향: 약 $3
- 설명: in-place 변환 가능, 약 20% 절감.

### [LOW] Stopped EC2 1대 (EBS만 청구 중)

- 위치: 전 리전
- 설명: 다시 켤 계획 없으면 종료: `i-00000000000000017`
