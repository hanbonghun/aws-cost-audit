"""Upload reports to S3, publish summary to SNS, post to Slack."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import Optional
from urllib.request import Request, urlopen

import boto3
from botocore.config import Config

log = logging.getLogger(__name__)
BOTO_CFG = Config(retries={"max_attempts": 5, "mode": "adaptive"})


def upload_to_s3(local_dir: str, bucket: str, prefix: str) -> str:
    """Upload all files in local_dir recursively to s3://bucket/prefix/. Returns S3 URI."""
    s3 = boto3.client("s3", config=BOTO_CFG)
    count = 0
    for root, _, files in os.walk(local_dir):
        for fname in files:
            local = os.path.join(root, fname)
            rel = os.path.relpath(local, local_dir)
            key = f"{prefix.rstrip('/')}/{rel}"
            content_type = (
                "text/markdown" if fname.endswith(".md")
                else "text/csv" if fname.endswith(".csv")
                else "application/json" if fname.endswith(".json")
                else "application/octet-stream"
            )
            s3.upload_file(local, bucket, key,
                           ExtraArgs={"ContentType": content_type})
            count += 1
    log.info("Uploaded %d files to s3://%s/%s", count, bucket, prefix)
    return f"s3://{bucket}/{prefix}"


def publish_to_sns(topic_arn: str, subject: str, body: str) -> None:
    sns = boto3.client("sns", region_name=topic_arn.split(":")[3], config=BOTO_CFG)
    # SNS subject 100-char limit
    subject = subject[:99] if len(subject) > 99 else subject
    sns.publish(TopicArn=topic_arn, Subject=subject, Message=body)
    log.info("Published to SNS: %s", topic_arn)


def post_to_slack(webhook_url: str, text: str, blocks: Optional[list] = None) -> None:
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    req = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=15) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Slack returned {resp.status}")
    log.info("Posted to Slack")


def build_summary(data: dict, s3_uri: str) -> dict:
    """Build a compact summary for SNS/Slack."""
    monthly = data["ce"]["monthly"]["ResultsByTime"]
    last_month = monthly[-2] if len(monthly) >= 2 else (monthly[-1] if monthly else None)
    last_cost = float(last_month["Total"]["UnblendedCost"]["Amount"]) if last_month else 0
    last_period = last_month["TimePeriod"]["Start"] if last_month else "—"

    ec2 = data["ec2"]
    idle = [e for e in ec2 if (e.get("AvgCPU") or 0) < 5]
    zero_albs = [a for a in data["albs"] if a.get("Category") == "ZERO-TRAFFIC"]
    zero_nats = [n for n in data["nats"] if n.get("Category") == "ZERO-TRAFFIC"]
    free_snaps = [s for s in data["snaps_dep"] if not s.get("BoundAMIs")]
    rds_idle = [r for r in data["rds"] if r.get("Verdict") == "IDLE"]

    sp_rec = (
        (data["sp_status"].get("sp_purchase") or {})
        .get("SavingsPlansPurchaseRecommendation", {})
        .get("SavingsPlansPurchaseRecommendationSummary", {})
    )
    sp_save = float(sp_rec.get("EstimatedMonthlySavingsAmount", 0) or 0)

    text_lines = [
        f"AWS Cost Audit — Account {data['account']}",
        f"  - {last_period} 비용: ${last_cost:,.2f}",
        f"  - Idle EC2: {len(idle)}/{len(ec2)}",
        f"  - Zero-traffic ALB: {len(zero_albs)}개",
        f"  - Zero-traffic NAT: {len(zero_nats)}개",
        f"  - RDS IDLE: {len(rds_idle)}개",
        f"  - 미사용 스냅샷: {len(free_snaps)}개",
    ]
    if sp_save > 0:
        text_lines.append(f"  - Compute SP 구매 추천 → ${sp_save}/mo 절감 가능")
    text_lines.append(f"  - 전체 리포트: {s3_uri}")

    return {
        "subject": f"AWS Cost Audit · ${last_cost:,.0f}/mo · {len(idle)} idle EC2",
        "text": "\n".join(text_lines),
    }
