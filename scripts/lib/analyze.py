"""
Analysis / classification logic.

Takes raw collected data from collect.py and produces:
  - Idle EC2 verdicts (TERMINATE/DOWNSIZE/INVESTIGATE/KEEP-BASTION)
  - Snapshot dependency check (bound to AMI vs orphan)
  - RDS / ElastiCache verdicts
  - NAT / ALB classifications
  - Cost summary computations
"""
from __future__ import annotations

import datetime as dt
from typing import Any

# Approximate ap-northeast-2 on-demand prices (USD/hour). Edit as needed.
EC2_PRICE = {
    "t2.micro": 0.0144, "t2.small": 0.0288, "t2.medium": 0.0576, "t2.large": 0.1152,
    "t3.nano": 0.0065, "t3.micro": 0.013, "t3.small": 0.026, "t3.medium": 0.052,
    "t3.large": 0.1043, "t3.xlarge": 0.2086, "t3.2xlarge": 0.4173,
    "t3a.medium": 0.0468,
    "t4g.nano": 0.0052, "t4g.micro": 0.0104, "t4g.small": 0.0208,
    "t4g.medium": 0.0416, "t4g.large": 0.0832,
    "m5.large": 0.118, "m5.xlarge": 0.236, "m5.2xlarge": 0.472, "m5.4xlarge": 0.944,
    "c5.large": 0.096, "c5.xlarge": 0.192,
    "r5.large": 0.151, "r5.xlarge": 0.302,
    "r6g.large": 0.1284, "r6g.xlarge": 0.2568,
    "r7i.large": 0.1764, "r7i.xlarge": 0.3528, "r7i.2xlarge": 0.7055, "r7i.4xlarge": 1.411,
}
EBS_PRICE = {
    "gp3": 0.0912, "gp2": 0.114, "io1": 0.142, "io2": 0.142,
    "st1": 0.051, "sc1": 0.0285, "standard": 0.08,
}
RDS_PRICE = {
    "db.t4g.micro": 0.020, "db.t4g.small": 0.040, "db.t4g.medium": 0.080,
    "db.t3.micro": 0.022, "db.t3.small": 0.044, "db.t3.medium": 0.088,
    "db.t2.micro": 0.024,
    "db.m5.large": 0.241, "db.m5.xlarge": 0.482, "db.m5.2xlarge": 0.964,
    "db.m6g.large": 0.219, "db.m6g.xlarge": 0.437,
    "db.r6g.large": 0.314, "db.r6g.xlarge": 0.628,
    "db.r5.large": 0.345, "db.r5.xlarge": 0.690,
}
RDS_STORAGE_PRICE = {"gp2": 0.138, "gp3": 0.115, "io1": 0.171}
EC_PRICE = {
    "cache.t4g.micro": 0.022, "cache.t4g.small": 0.045, "cache.t4g.medium": 0.090,
    "cache.t3.micro": 0.026, "cache.t3.small": 0.051, "cache.t3.medium": 0.102,
    "cache.r6g.large": 0.226, "cache.r6g.xlarge": 0.452,
    "cache.m6g.large": 0.187,
}
HOURS_PER_MONTH = 730


def classify_ec2_idle(e: dict) -> dict:
    """Add Verdict/Rationale based on CPU/Network/LB membership."""
    name = (e.get("Name") or "").lower()
    avg = e.get("AvgCPU") or 0
    mx = e.get("MaxCPU") or 0
    net = (e.get("NetIn30dGiB") or 0) + (e.get("NetOut30dGiB") or 0)
    has_lb = bool(e.get("TargetGroupMemberships"))

    if "bastion" in name or "jump" in name:
        verdict, rationale = "KEEP-BASTION", \
            f"Bastion/jump host (low CPU normal); consider t4g.nano (~$3.80/mo)"
    elif has_lb and not net:
        verdict, rationale = "INVESTIGATE-LB", \
            f"LB-attached but no traffic 30d — confirm ALB request count"
    elif avg < 1 and mx < 10 and net < 0.5 and not has_lb:
        verdict, rationale = "TERMINATE-CANDIDATE", \
            f"avg {avg:.2f}%, max {mx:.2f}%, net {net:.2f} GiB, no LB"
    elif avg < 2 and mx < 20:
        verdict, rationale = "DOWNSIZE", \
            f"low usage (avg {avg:.2f}%, max {mx:.2f}%) — downsize 1-2 sizes"
    elif has_lb:
        verdict, rationale = "INVESTIGATE-LB", \
            f"LB-attached (avg {avg:.2f}%, max {mx:.2f}%) — confirm LB traffic"
    else:
        verdict, rationale = "REVIEW", \
            f"avg {avg:.2f}%, max {mx:.2f}%, net {net:.2f} GiB"
    e["Verdict"] = verdict
    e["Rationale"] = rationale
    return e


def ec2_monthly_cost(instance_type: str, ebs_gib: int = 0) -> float:
    hourly = EC2_PRICE.get(instance_type)
    compute = hourly * HOURS_PER_MONTH if hourly else 0
    ebs = ebs_gib * 0.0912  # gp3 baseline assumption
    return round(compute + ebs, 2)


def rds_monthly_cost(r: dict) -> float | None:
    hourly = RDS_PRICE.get(r["Class"])
    if not hourly:
        return None
    multi = 2 if r.get("MultiAZ") else 1
    compute = hourly * HOURS_PER_MONTH * multi
    storage = (r.get("Storage") or 0) * RDS_STORAGE_PRICE.get(r.get("StorageType"), 0.13) * multi
    return round(compute + storage, 2)


def rds_verdict(r: dict) -> tuple[str, str]:
    cpu = r.get("CPU_avg") or 99
    conn = r.get("Conn_avg") or 99
    if conn < 1 and cpu < 5:
        return "IDLE", f"avg conn {conn:.2f}, cpu {cpu:.2f}%"
    if cpu < 5 and not r.get("MultiAZ"):
        return "DOWNSIZE", f"cpu {cpu:.2f}% — check next smaller size"
    return "OK", ""


def ec_verdict(c: dict) -> tuple[str, str]:
    cpu = c.get("CPU_avg") or 99
    conn = c.get("Conn_avg") or 99
    if cpu < 2 and conn < 5:
        return "LIKELY-IDLE", f"avg cpu {cpu:.2f}%, conn {conn:.1f}"
    return "OK", ""


def ec_monthly_cost(c: dict) -> float | None:
    hourly = EC_PRICE.get(c["Type"])
    if not hourly:
        return None
    return round(hourly * HOURS_PER_MONTH * (c.get("NumNodes") or 1), 2)


def snapshot_dependency(snaps: list[dict], my_amis: list[dict]) -> list[dict]:
    """Annotate each snapshot with BoundAMIs[]."""
    snap_to_ami: dict[str, list[dict]] = {}
    for a in my_amis:
        for s in (a.get("Snapshots") or []):
            snap_to_ami.setdefault(s, []).append({
                "AMI": a["ImageId"], "Name": a.get("Name"), "State": a.get("State"),
            })
    out = []
    for s in snaps:
        out.append({**s, "BoundAMIs": snap_to_ami.get(s["SnapshotId"], [])})
    return out


def alb_classify(albs: list[dict]) -> list[dict]:
    out = []
    for a in albs:
        req = a.get("Req30dTotal", 0)
        if req == 0:
            cat = "ZERO-TRAFFIC"
        elif req < 1000 * 30:
            cat = "LOW-TRAFFIC"
        else:
            cat = "NORMAL"
        out.append({**a, "Category": cat})
    return out


def nat_classify(nats: list[dict]) -> list[dict]:
    out = []
    for n in nats:
        gib = n.get("GiB30d", 0)
        if gib == 0:
            cat = "ZERO-TRAFFIC"
        elif gib < 1:
            cat = "VERY-LOW"
        elif gib < 10:
            cat = "LOW"
        else:
            cat = "NORMAL"
        out.append({**n, "Category": cat})
    return out


# ──────────────────────────────────────────────────────────────────────
# Compute Optimizer summary
# ──────────────────────────────────────────────────────────────────────

def co_savings_summary(co: dict) -> dict:
    summary = {
        "ec2_count": len(co.get("instanceRecommendations") or []),
        "ec2_savings": 0.0,
        "ebs_count": len(co.get("volumeRecommendations") or []),
        "ebs_savings": 0.0,
        "lambda_count": len(co.get("lambdaFunctionRecommendations") or []),
        "lambda_savings": 0.0,
        "asg_count": len(co.get("autoScalingGroupRecommendations") or []),
    }
    for r in co.get("instanceRecommendations") or []:
        opts = r.get("recommendationOptions", [])
        if opts:
            summary["ec2_savings"] += float(
                (opts[0].get("savingsOpportunity") or {}).get("estimatedMonthlySavings", {}).get("value", 0) or 0
            )
    for r in co.get("volumeRecommendations") or []:
        opts = r.get("volumeRecommendationOptions", [])
        if opts:
            summary["ebs_savings"] += float(
                (opts[0].get("savingsOpportunity") or {}).get("estimatedMonthlySavings", {}).get("value", 0) or 0
            )
    for r in co.get("lambdaFunctionRecommendations") or []:
        opts = r.get("memorySizeRecommendationOptions", [])
        if opts:
            summary["lambda_savings"] += float(
                (opts[0].get("savingsOpportunity") or {}).get("estimatedMonthlySavings", {}).get("value", 0) or 0
            )
    return summary
