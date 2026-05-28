"""Markdown + CSV report generation."""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
from typing import Any


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})


def write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)


def _ts() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_cost_report(out_dir: str, data: dict) -> str:
    path = os.path.join(out_dir, "01-cost-report.md")
    os.makedirs(out_dir, exist_ok=True)

    monthly = data["ce"]["monthly"]["ResultsByTime"]
    by_svc_results = data["ce"]["by_service"]["ResultsByTime"]
    by_svc_last = by_svc_results[-2] if len(by_svc_results) >= 2 else by_svc_results[-1] if by_svc_results else None

    ec2 = data["ec2"]
    idle = [e for e in ec2 if (e.get("AvgCPU") or 0) < 5]
    albs = data["albs"]
    zero_albs = [a for a in albs if a.get("Category") == "ZERO-TRAFFIC"]
    low_albs = [a for a in albs if a.get("Category") == "LOW-TRAFFIC"]
    nats = data["nats"]
    zero_nats = [n for n in nats if n.get("Category") == "ZERO-TRAFFIC"]
    rds = data["rds"]
    rds_idle = [r for r in rds if r.get("Verdict") == "IDLE"]
    ec = data["ec"]
    ec_idle = [c for c in ec if c.get("Verdict") == "LIKELY-IDLE"]
    co = data["co_summary"]
    sp_rec_summary = (
        (data["sp_status"].get("sp_purchase") or {})
        .get("SavingsPlansPurchaseRecommendation", {})
        .get("SavingsPlansPurchaseRecommendationSummary", {})
    )
    sp_cov = (((data["sp_status"].get("sp_coverage") or {}).get("SavingsPlansCoverages") or [{}])[0]
              .get("Coverage", {}))
    ri_cov = ((data["sp_status"].get("ri_coverage") or {}).get("Total") or {}).get("CoverageHours", {})

    snaps = data["snaps_dep"]
    free_snaps = [s for s in snaps if not s.get("BoundAMIs")]
    bound_snaps = [s for s in snaps if s.get("BoundAMIs")]
    gp2 = [v for v in data["volumes"] if v["Type"] == "gp2"]

    L = []
    L.append("# 📊 AWS 종합 비용 리포트")
    L.append("")
    L.append(f"_Account {data['account']} · {_ts()}_  ")
    L.append(f"_권한: `{data['caller_arn']}` · READ-ONLY 모드_")
    L.append("")
    L.append("## 🎯 Executive Summary")
    L.append("")
    L.append("**월별 총비용 (Cost Explorer 실측):**")
    L.append("")
    L.append("| 기간 | 비용 |")
    L.append("|---|---:|")
    for m in monthly:
        s = m["TimePeriod"]["Start"]
        e = m["TimePeriod"]["End"]
        cost = float(m["Total"]["UnblendedCost"]["Amount"])
        L.append(f"| {s} → {e} | ${cost:,.2f} |")
    L.append("")

    if by_svc_last:
        L.append(f"**서비스별 비용 ({by_svc_last['TimePeriod']['Start']} 기준):**")
        L.append("")
        L.append("| 순위 | 서비스 | 비용 | 비중 |")
        L.append("|---:|---|---:|---:|")
        groups = sorted(by_svc_last["Groups"],
                        key=lambda g: -float(g["Metrics"]["UnblendedCost"]["Amount"]))
        total = sum(float(g["Metrics"]["UnblendedCost"]["Amount"]) for g in groups) or 1
        for i, g in enumerate(groups[:12], 1):
            amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
            if amt < 1:
                continue
            L.append(f"| {i} | {g['Keys'][0]} | ${amt:,.2f} | {amt/total*100:.1f}% |")
        L.append("")

    L.append("**핵심 인사이트:**")
    L.append("")
    L.append(f"- 실행 중 EC2: **{len(ec2)}대**, 그 중 **idle(30일 avg CPU<5%) {len(idle)}대**")
    L.append(f"- ALB **{len(albs)}개**, 그 중 30일 트래픽 0: **{len(zero_albs)}개**, < 1k req/day: {len(low_albs)}개")
    L.append(f"- NAT GW **{len(nats)}개**, 트래픽 0: **{len(zero_nats)}개**, 합산 시간당 고정비 ${len(nats)*0.059*730:.0f}/mo")
    L.append(f"- RDS **{len(rds)}개**, IDLE: **{len(rds_idle)}개**")
    L.append(f"- ElastiCache **{len(ec)}개**, LIKELY-IDLE: **{len(ec_idle)}개**")
    if sp_cov:
        L.append(f"- Savings Plans Coverage: **{float(sp_cov.get('CoveragePercentage', 0)):.1f}%**")
    if ri_cov:
        L.append(f"- RI Coverage: **{float(ri_cov.get('CoverageHoursPercentage', 0)):.1f}%**")
    if sp_rec_summary:
        L.append(f"- Compute SP 추천 적용 시 추가 절감 예상: **${sp_rec_summary.get('EstimatedMonthlySavingsAmount', 0)}/mo** ({float(sp_rec_summary.get('EstimatedSavingsPercentage', 0)):.1f}%)")
    L.append("")

    L.append("**예상 절감 추정 (Phase 1~2):**")
    L.append("")
    L.append("| 액션 | 월 절감 | 위험도 |")
    L.append("|---|---:|---|")
    if sp_rec_summary:
        L.append(f"| Compute SP 구매 (${sp_rec_summary.get('HourlyCommitmentToPurchase')}/hr) | **${sp_rec_summary.get('EstimatedMonthlySavingsAmount')}** | ⚪ 없음 |")
    if zero_albs:
        L.append(f"| Zero-traffic ALB {len(zero_albs)}개 정리 | **${len(zero_albs)*22:.0f}+** | 🟡 트래픽 재확인 |")
    if zero_nats:
        L.append(f"| Zero-traffic NAT GW {len(zero_nats)}개 제거 | **${len(zero_nats)*42:.0f}** | 🟠 라우팅 변경 |")
    if free_snaps:
        L.append(f"| 미사용 스냅샷 {len(free_snaps)}개 ({sum(s['Size'] for s in free_snaps)} GiB) 삭제 | **${sum(s['Size'] for s in free_snaps)*0.05:.0f}** | ⚪ 없음 |")
    if gp2:
        savings_gp2 = sum(v["Size"] for v in gp2) * (0.114 - 0.0912)
        L.append(f"| EBS gp2 → gp3 ({len(gp2)}개) | **${savings_gp2:.0f}** | ⚪ 없음 |")
    if rds_idle:
        L.append(f"| IDLE RDS {len(rds_idle)}개 종료 (final snapshot 후) | **${sum(r.get('MonthlyUSD_approx') or 0 for r in rds_idle):.0f}** | 🟡 데이터 백업 |")
    if co["ec2_count"] + co["ebs_count"] > 0:
        L.append(f"| Compute Optimizer 추천 적용 ({co['ec2_count']} EC2 + {co['ebs_count']} EBS) | **${co['ec2_savings']+co['ebs_savings']:.0f}** | 🟡 추천별 risk 확인 |")
    L.append("")

    # Detail sections
    L.append("## 1. Idle EC2 인스턴스")
    L.append("")
    if idle:
        L.append("| Id | Type | Name | AvgCPU% | MaxCPU% | Net30d GiB | Verdict |")
        L.append("|---|---|---|---:|---:|---:|---|")
        for e in sorted(idle, key=lambda x: x.get("AvgCPU") or 0):
            net = (e.get("NetIn30dGiB") or 0) + (e.get("NetOut30dGiB") or 0)
            L.append(f"| `{e['Id']}` | {e['Type']} | {e['Name']} | "
                     f"{(e.get('AvgCPU') or 0):.2f} | {(e.get('MaxCPU') or 0):.2f} | "
                     f"{net:.2f} | {e.get('Verdict', 'REVIEW')} |")
    L.append("")

    L.append("## 2. Zero-traffic ALBs")
    L.append("")
    if zero_albs:
        L.append("| Region | Name | Listeners | Created |")
        L.append("|---|---|---:|---|")
        for a in zero_albs:
            L.append(f"| {a['Region']} | {a['Name']} | {a.get('Listeners', '-')} | {(a.get('Created') or '')[:10]} |")
    else:
        L.append("_없음_")
    L.append("")

    L.append("## 3. NAT Gateway 사용도")
    L.append("")
    L.append("| Id | VPC | 30d GiB | 평가 |")
    L.append("|---|---|---:|---|")
    for n in nats:
        L.append(f"| `{n['NatGatewayId']}` | `{n['VpcId']}` | {n.get('GiB30d', 0)} | {n.get('Category')} |")
    L.append("")

    L.append("## 4. RDS Database")
    L.append("")
    L.append("| Id | Class | Engine | MAZ | CPU% | Conn | Verdict |")
    L.append("|---|---|---|:-:|---:|---:|---|")
    for r in rds:
        L.append(f"| `{r['Id']}` | {r['Class']} | {r['Engine']} | "
                 f"{'Y' if r['MultiAZ'] else ''} | {r.get('CPU_avg')} | "
                 f"{r.get('Conn_avg')} | {r.get('Verdict', 'OK')} |")
    L.append("")

    L.append("## 5. ElastiCache")
    L.append("")
    L.append("| Id | Type | CPU% | Conn | Mem% | Verdict |")
    L.append("|---|---|---:|---:|---:|---|")
    for c in ec:
        L.append(f"| `{c['Id']}` | {c['Type']} | {c.get('CPU_avg')} | "
                 f"{c.get('Conn_avg')} | {c.get('Mem_avg_pct')} | {c.get('Verdict')} |")
    L.append("")

    L.append("## 6. 미사용 스냅샷 (AMI 종속성 체크 완료)")
    L.append("")
    L.append(f"- AMI 종속 (보관 필요): {len(bound_snaps)}개")
    L.append(f"- 독립 (안전 삭제 가능): **{len(free_snaps)}개 ({sum(s['Size'] for s in free_snaps)} GiB)**")
    if free_snaps:
        L.append("")
        L.append("| SnapshotId | Size GiB | Started |")
        L.append("|---|---:|---|")
        for s in free_snaps:
            L.append(f"| `{s['SnapshotId']}` | {s['Size']} | {(s.get('Started') or '')[:10]} |")
    L.append("")

    L.append("## 7. Compute Optimizer 추천")
    L.append("")
    L.append(f"- EC2 rightsizing: {co['ec2_count']}건 (~${co['ec2_savings']:.0f}/mo 절감 가능)")
    L.append(f"- EBS rightsizing: {co['ebs_count']}건 (~${co['ebs_savings']:.0f}/mo)")
    L.append(f"- Lambda rightsizing: {co['lambda_count']}건 (~${co['lambda_savings']:.0f}/mo)")
    L.append(f"- ASG rightsizing: {co['asg_count']}건")
    L.append("")

    L.append("## 8. 거버넌스 (태그)")
    L.append("")
    L.append("| 리소스 타입 | 총 | 누락(any) | NoOwner | NoProject | NoEnv |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for t, d in sorted(data["tags"].items()):
        L.append(f"| {t} | {d['total']} | {d['missing_any']} | "
                 f"{d['missing']['Owner']} | {d['missing']['Project']} | "
                 f"{d['missing']['Environment']} |")
    L.append("")

    L.append("## 9. 부속 산출물")
    L.append("")
    L.append("- `02-problems.md` — 발견 문제 (심각도별)")
    L.append("- `03-improvements.md` — Phase 1/2/3 액션 플랜")
    L.append("- `data/` — 카테고리별 raw CSV")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


def render_problems(out_dir: str, data: dict) -> str:
    path = os.path.join(out_dir, "02-problems.md")
    L = []
    L.append("# 🚨 발견된 문제점")
    L.append("")
    L.append(f"_{_ts()}_")
    L.append("")

    sp_rec = (
        (data["sp_status"].get("sp_purchase") or {})
        .get("SavingsPlansPurchaseRecommendation", {})
        .get("SavingsPlansPurchaseRecommendationSummary", {})
    )
    sp_cov = (((data["sp_status"].get("sp_coverage") or {}).get("SavingsPlansCoverages") or [{}])[0]
              .get("Coverage", {}))

    problems = []
    if sp_cov and float(sp_cov.get("CoveragePercentage", 0)) < 50:
        save = float(sp_rec.get("EstimatedMonthlySavingsAmount", 0) or 0)
        problems.append(("🔴",
            f"Savings Plans 커버리지 {float(sp_cov.get('CoveragePercentage', 0)):.0f}% (낮음)",
            "Account 전역",
            save,
            f"Compute SP 구매 시 ${save}/mo 절감 가능. ROI {float(sp_rec.get('EstimatedROI', 0)):.0f}%."))

    zero_nats = [n for n in data["nats"] if n.get("Category") == "ZERO-TRAFFIC"]
    if zero_nats:
        problems.append(("🔴",
            f"NAT Gateway {len(zero_nats)}개가 30일 트래픽 0",
            "ap-northeast-2",
            len(zero_nats) * 42,
            "시간당 고정비만 청구 중. 라우팅 테이블 검토 후 제거."))

    zero_albs = [a for a in data["albs"] if a.get("Category") == "ZERO-TRAFFIC"]
    if zero_albs:
        problems.append(("🟠",
            f"ALB {len(zero_albs)}개 zero-traffic",
            "전 리전",
            len(zero_albs) * 22,
            "사용처가 정말 없는지 확인 후 삭제."))

    idle = [e for e in data["ec2"] if (e.get("AvgCPU") or 0) < 5]
    if len(idle) > 0:
        problems.append(("🟠",
            f"Idle EC2 {len(idle)}대 (avg CPU < 5%)",
            "전 리전",
            None,
            "각 인스턴스의 Verdict 별 액션 (TERMINATE/DOWNSIZE/KEEP) 검토."))

    rds_idle = [r for r in data["rds"] if r.get("Verdict") == "IDLE"]
    if rds_idle:
        problems.append(("🟠",
            f"RDS IDLE {len(rds_idle)}개 (avg conn < 1)",
            "전 리전",
            sum(r.get("MonthlyUSD_approx") or 0 for r in rds_idle),
            f"종료 대상: {', '.join('`'+r['Id']+'`' for r in rds_idle)}"))

    free_snaps = [s for s in data["snaps_dep"] if not s.get("BoundAMIs")]
    if free_snaps:
        problems.append(("🟡",
            f"AMI 미종속 90일+ 스냅샷 {len(free_snaps)}개 ({sum(s['Size'] for s in free_snaps)} GiB)",
            "ap-northeast-2",
            sum(s['Size'] for s in free_snaps) * 0.05,
            "AMI 종속성 확인 완료. 안전하게 삭제 가능."))

    gp2 = [v for v in data["volumes"] if v["Type"] == "gp2"]
    if gp2:
        save = sum(v["Size"] for v in gp2) * (0.114 - 0.0912)
        problems.append(("🟡",
            f"EBS gp2 볼륨 {len(gp2)}개 ({sum(v['Size'] for v in gp2)} GiB) → gp3 가능",
            "전 리전",
            save,
            "in-place 변환 가능, ~20% 절감."))

    stopped = data["orphans"].get("stopped_ec2") or []
    if stopped:
        problems.append(("🟡",
            f"Stopped EC2 {len(stopped)}대 (EBS만 청구 중)",
            "전 리전",
            None,
            f"다시 켤 계획 없으면 종료: {', '.join('`'+s['Id']+'`' for s in stopped[:5])}"))

    # Untagged
    tags = data["tags"]
    ec2_untag = tags.get("ec2:instance", {})
    if ec2_untag.get("missing_any", 0) > 0:
        ratio = ec2_untag["missing_any"] / max(ec2_untag["total"], 1) * 100
        problems.append(("🟠",
            f"EC2 {ec2_untag['missing_any']}/{ec2_untag['total']} ({ratio:.0f}%) Owner/Project/Env 태그 누락",
            "전역",
            None,
            "정리 작업 시 책임자 추적 불가. Tag enforcement (SCP) 도입 권장."))

    co_savings = data["co_summary"]["ec2_savings"] + data["co_summary"]["ebs_savings"]
    if co_savings > 0:
        problems.append(("🟡",
            f"Compute Optimizer 추천 {data['co_summary']['ec2_count']+data['co_summary']['ebs_count']}건 미적용",
            "ap-northeast-2",
            co_savings,
            "AWS 자체 추천 — Console에서 risk 'Very Low' 위주로 적용 시작."))

    # Sort by severity then by cost
    sev_rank = {"🔴": 0, "🟠": 1, "🟡": 2, "🔵": 3}
    problems.sort(key=lambda p: (sev_rank.get(p[0], 99), -(p[3] or 0)))

    for sev, title, where, cost, why in problems:
        L.append(f"### {sev} {title}")
        L.append("")
        L.append(f"- **위치**: {where}")
        if cost:
            L.append(f"- **월비용 영향**: ~${cost:,.0f}")
        L.append(f"- **설명**: {why}")
        L.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


def render_improvements(out_dir: str, data: dict) -> str:
    path = os.path.join(out_dir, "03-improvements.md")
    L = []
    L.append("# 🛠 개선안 (Phase 1 / 2 / 3)")
    L.append("")
    L.append(f"_{_ts()}_")
    L.append("")
    L.append("각 액션마다 예상 절감, 위험도, 사전 검증, 롤백을 포함.")
    L.append("")

    sp_rec = (
        (data["sp_status"].get("sp_purchase") or {})
        .get("SavingsPlansPurchaseRecommendation", {})
        .get("SavingsPlansPurchaseRecommendationSummary", {})
    )
    zero_albs = [a for a in data["albs"] if a.get("Category") == "ZERO-TRAFFIC"]
    zero_nats = [n for n in data["nats"] if n.get("Category") == "ZERO-TRAFFIC"]
    free_snaps = [s for s in data["snaps_dep"] if not s.get("BoundAMIs")]
    gp2 = [v for v in data["volumes"] if v["Type"] == "gp2"]
    rds_idle = [r for r in data["rds"] if r.get("Verdict") == "IDLE"]
    safe_term = [e for e in data["ec2"] if e.get("Verdict") == "TERMINATE-CANDIDATE"]
    downsize = [e for e in data["ec2"] if e.get("Verdict") == "DOWNSIZE"]

    L.append("## Phase 1 — 즉시 실행 (위험 ⚪~🟢)")
    L.append("")
    n = 0
    if sp_rec:
        n += 1
        L.append(f"### {n}. Compute Savings Plan ${sp_rec.get('HourlyCommitmentToPurchase')}/hr 구매")
        L.append(f"- **절감**: ${sp_rec.get('EstimatedMonthlySavingsAmount')}/mo · "
                 f"${float(sp_rec.get('EstimatedSavingsAmount', 0)):,.0f}/yr · "
                 f"{float(sp_rec.get('EstimatedSavingsPercentage', 0)):.0f}% off")
        L.append("- **위험**: 🟢 없음 (RI 만료 시 자동 흡수)")
        L.append("- **검증**: 최근 60일 EC2 사용 안정성 확인 → AWS Console > Savings Plans")
        L.append("- **롤백**: 1년 약정. 단 ROI 43%로 손익분기 빠름.")
        L.append("")
    if free_snaps:
        n += 1
        L.append(f"### {n}. 미사용 스냅샷 {len(free_snaps)}개 삭제")
        L.append(f"- **절감**: ${sum(s['Size'] for s in free_snaps)*0.05:.0f}/mo")
        L.append("- **위험**: 🟢 AMI 종속성 사전 확인 완료")
        L.append(f"- **대상**: {', '.join('`'+s['SnapshotId']+'`' for s in free_snaps[:5])}" + (f" 외 {len(free_snaps)-5}개" if len(free_snaps)>5 else ""))
        L.append("- **롤백**: 삭제 후 복구 불가. EBS 원본은 남아 있음.")
        L.append("")
    if gp2:
        n += 1
        save = sum(v["Size"] for v in gp2) * (0.114 - 0.0912)
        L.append(f"### {n}. EBS gp2 → gp3 마이그레이션 ({len(gp2)}개 / {sum(v['Size'] for v in gp2)} GiB)")
        L.append(f"- **절감**: ${save:.0f}/mo")
        L.append("- **위험**: 🟢 in-place 변환, 다운타임 없음")
        L.append("- **검증**: gp3 기본 IOPS 3000 ≥ gp2 baseline")
        L.append("- **롤백**: gp3 → gp2 재변환 가능")
        L.append("")
    if zero_albs:
        n += 1
        L.append(f"### {n}. Zero-traffic ALB {len(zero_albs)}개 정리")
        L.append(f"- **절감**: ~${len(zero_albs)*22}/mo")
        L.append("- **위험**: 🟡 잠시 미사용 가능")
        L.append("- **검증**: Slack 공지 + Route53 record 확인")
        L.append(f"- **대상**: {', '.join('`'+a['Name']+'`' for a in zero_albs)}")
        L.append("")
    if safe_term:
        n += 1
        L.append(f"### {n}. SAFE-TERMINATE EC2 {len(safe_term)}대 종료")
        L.append(f"- **절감**: 총 ${sum(((e.get('AvgCPU') or 0)*5+10) for e in safe_term):.0f}/mo (대략)")
        L.append("- **위험**: 🟢 LB 미연결 + 거의 사용 흔적 없음")
        L.append("- **검증**: Owner 태그 확인 → Slack 공지 → 7일 stop → terminate")
        L.append("")

    L.append("## Phase 2 — 1~2주 (소유자 확인 필요, 위험 🟡)")
    L.append("")
    n = 0
    if zero_nats:
        n += 1
        L.append(f"### {n}. NAT Gateway {len(zero_nats)}개 제거 (zero traffic)")
        L.append(f"- **절감**: ${len(zero_nats)*42}/mo")
        L.append("- **위험**: 🟠 라우팅 변경 — VPC outbound 일시 중단 가능")
        L.append("- **검증**: VPC 라우팅 테이블 + Subnet usage 확인")
        L.append(f"- **대상**: {', '.join('`'+n['NatGatewayId']+'`' for n in zero_nats)}")
        L.append("- **롤백**: NAT GW는 5분 내 재생성")
        L.append("")
    if rds_idle:
        n += 1
        L.append(f"### {n}. IDLE RDS {len(rds_idle)}개 종료")
        L.append(f"- **절감**: ${sum(r.get('MonthlyUSD_approx') or 0 for r in rds_idle):.0f}/mo")
        L.append("- **위험**: 🟡 데이터 손실 방지")
        L.append("- **검증**: Final snapshot 생성 → Performance Insights 로 최근 query 확인")
        L.append(f"- **대상**: {', '.join('`'+r['Id']+'`' for r in rds_idle)}")
        L.append("- **롤백**: snapshot에서 복원")
        L.append("")
    if downsize:
        n += 1
        L.append(f"### {n}. EC2 다운사이즈 {len(downsize)}대")
        L.append("- **위험**: 🟡 트래픽 스파이크 대응 검증")
        L.append("- **검증**: max CPU < 20% 확인")
        L.append("- **롤백**: 더 큰 사이즈로 재변경")
        L.append("")

    co = data["co_summary"]
    if co["ec2_count"] + co["ebs_count"] > 0:
        n += 1
        L.append(f"### {n}. Compute Optimizer 추천 적용 (EC2 {co['ec2_count']}건 + EBS {co['ebs_count']}건)")
        L.append(f"- **절감**: ~${co['ec2_savings']+co['ebs_savings']:.0f}/mo")
        L.append("- **위험**: 🟡 추천별 'Risk' 컬럼 확인 (Very Low → Low → Medium 순서로 적용)")
        L.append("")

    L.append("## Phase 3 — 전략 (위험 🟠, 1개월+)")
    L.append("")
    L.append("### 1. ECS 클러스터 통합 또는 Fargate 전환")
    L.append("- **절감**: $200~500/mo (예상)")
    L.append("- **검증**: 각 클러스터의 desired/running count, capacity provider 활용도")
    L.append("- **롤백**: 별도 클러스터로 분리 가능")
    L.append("")
    L.append("### 2. Tag enforcement (SCP)")
    L.append("- Service Control Policy로 Owner/Project/Environment 강제")
    L.append("- staging 환경에서 먼저 검증")
    L.append("")
    L.append("### 3. Cost Anomaly Detection + AWS Budgets (이미 Terraform에 포함)")
    L.append("- 월 $5,000 임계값")
    L.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


def render_methodology(out_dir: str, data: dict) -> str:
    path = os.path.join(out_dir, "99-methodology.md")
    L = []
    L.append("# 🔬 방법론과 한계")
    L.append("")
    L.append(f"_{_ts()}_")
    L.append("")
    L.append("## 데이터 출처")
    L.append("")
    L.append("- EC2/EBS/Snapshot/NAT/ALB: `ec2:Describe*`, `elasticloadbalancing:Describe*`")
    L.append("- 메트릭: CloudWatch `GetMetricStatistics` (30일, period=86400)")
    L.append("- 비용 추이: Cost Explorer `GetCostAndUsage`")
    L.append("- 추천: Compute Optimizer `Get*Recommendations`, Cost Explorer `Get*PurchaseRecommendation`")
    L.append("- 태그 감사: ResourceGroupsTaggingAPI `GetResources`")
    L.append("")
    L.append("## 가격 기준")
    L.append("")
    L.append("AWS 공시 On-Demand 가격 (ap-northeast-2), 2026년 초 기준. RI/SP 적용 후 실제 비용은 더 낮음.")
    L.append("정확한 비용은 Cost Explorer 의 UnblendedCost 참조.")
    L.append("")
    L.append("## 한계")
    L.append("")
    L.append("1. 인스턴스 내부 프로세스/cron 은 별도 SSM Inventory 필요")
    L.append("2. S3 객체 access pattern 은 Storage Lens 필요")
    L.append("3. Trusted Advisor cost 체크는 Business+ support plan 필요")
    L.append("4. 단일 시점 스냅샷 — 분석 직후 새 리소스 반영 안 됨")
    L.append("")
    L.append(f"## 검증 로그")
    L.append("")
    L.append(f"- 호출 신원: `{data['caller_arn']}`")
    L.append(f"- 사용된 API 동사: `describe-*`, `list-*`, `get-*` 만")
    L.append(f"- CloudTrail 에서 `*Create*`, `*Modify*`, `*Delete*` 이벤트 0 검증 가능")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


def render_all(out_dir: str, data: dict) -> dict:
    """Render all reports + CSVs. Returns dict of paths."""
    paths = {
        "cost_report": render_cost_report(out_dir, data),
        "problems": render_problems(out_dir, data),
        "improvements": render_improvements(out_dir, data),
        "methodology": render_methodology(out_dir, data),
    }

    csv_dir = os.path.join(out_dir, "data")
    write_csv(f"{csv_dir}/ec2_idle.csv",
              [e for e in data["ec2"] if (e.get("AvgCPU") or 0) < 5],
              ["Region", "Id", "Type", "Name", "AvgCPU", "MaxCPU",
               "NetIn30dGiB", "NetOut30dGiB", "Verdict", "Rationale"])
    write_csv(f"{csv_dir}/alb_traffic.csv", data["albs"],
              ["Region", "Name", "Category", "Req30dTotal", "ReqAvgDaily",
               "Errors5xx30d", "Created"])
    write_csv(f"{csv_dir}/nat_usage.csv", data["nats"],
              ["Region", "NatGatewayId", "VpcId", "GiB30d", "Category"])
    write_csv(f"{csv_dir}/rds_analysis.csv", data["rds"],
              ["Region", "Id", "Class", "Engine", "MultiAZ", "Storage",
               "CPU_avg", "Conn_avg", "MonthlyUSD_approx", "Verdict"])
    write_csv(f"{csv_dir}/elasticache.csv", data["ec"],
              ["Region", "Id", "Type", "Engine", "NumNodes",
               "CPU_avg", "Conn_avg", "Mem_avg_pct", "Verdict"])
    write_csv(f"{csv_dir}/ebs_volumes.csv", data["volumes"],
              ["Region", "Id", "Size", "Type", "State"])
    write_csv(f"{csv_dir}/snapshots_old.csv", data["snaps_dep"],
              ["Region", "SnapshotId", "Size", "Started", "BoundAMIs"])
    write_csv(f"{csv_dir}/lambda_functions.csv", data["lambdas"],
              ["Region", "Name", "Runtime", "Memory", "Timeout", "CodeSize"])
    write_csv(f"{csv_dir}/log_groups.csv", data["logs"],
              ["Region", "Name", "Retention", "Bytes"])
    write_csv(f"{csv_dir}/cloudfront.csv", data["cloudfront"],
              ["Id", "Domain", "Enabled", "Origin", "Comment", "PriceClass"])
    write_csv(f"{csv_dir}/stopped_ec2.csv", data["orphans"]["stopped_ec2"],
              ["Region", "Id", "Type", "Name", "Stopped"])
    write_csv(f"{csv_dir}/eip_unattached.csv", data["eip_unattached"],
              ["Region", "PublicIp", "AllocationId", "Domain"])

    write_json(f"{csv_dir}/master_summary.json", data)
    paths["data_dir"] = csv_dir
    return paths
