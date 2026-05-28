#!/usr/bin/env python3
"""
aws-cost-audit — main entrypoint.

Runs all 17 investigations and produces markdown + CSV reports.
Uploads to S3, optionally publishes to SNS and Slack.

ENV:
  AWS_ROLE_ARN         (assumed by GitHub Actions via OIDC - automatic in CI)
  S3_REPORT_BUCKET     (required) target S3 bucket for report uploads
  SNS_TOPIC_ARN        (optional) SNS topic for summary email
  SLACK_WEBHOOK_URL    (optional) Slack incoming webhook
  AWS_REGION           (default ap-northeast-2)
  OUTPUT_DIR           (default ./audit-output) local output dir
  ENABLE_S3_LIFECYCLE  (default true) enable lifecycle audit (slow on 100+ buckets)
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

# Make `lib` importable when invoked from any cwd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib import collect, analyze, report, notify  # noqa: E402

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("audit")


def main() -> int:
    start = datetime.now(timezone.utc)
    out_root = os.environ.get("OUTPUT_DIR", "./audit-output")
    today = start.strftime("%Y-%m-%d")
    out_dir = os.path.join(out_root, today)
    os.makedirs(out_dir, exist_ok=True)

    log.info("==== aws-cost-audit ====")

    # 1. Identity check
    caller = collect.caller_identity()
    log.info("Identity: %s", caller["Arn"])
    if "readonly" not in caller["Arn"].lower() and "audit" not in caller["Arn"].lower():
        log.warning("Caller ARN does not contain 'readonly' or 'audit' — be cautious.")

    # 2. Regions
    regions = collect.opted_in_regions()
    log.info("Regions: %d opted-in", len(regions))

    # 3. Inventory (parallel across regions)
    log.info("Collecting EC2 / EBS / EIP / Snapshots / NAT / LB ...")
    ec2 = collect.collect_running_ec2(regions)
    log.info("  Running EC2: %d", len(ec2))
    ebs_unattached = collect.collect_unattached_ebs(regions)
    eip_unattached = collect.collect_unattached_eips(regions)
    snaps = collect.collect_old_snapshots(regions)
    nats = collect.collect_nat_gateways(regions)
    lbs = collect.collect_load_balancers(regions)
    log.info("  EBS unattached: %d, EIP: %d, old snaps: %d, NAT: %d, LB: %d",
             len(ebs_unattached), len(eip_unattached), len(snaps), len(nats), len(lbs))

    # 4. Enrich EC2 with CPU + network
    log.info("Enriching EC2 with CloudWatch CPU/Network ...")
    ec2 = collect.enrich_ec2_cpu(ec2)
    ec2 = collect.enrich_ec2_network(ec2)
    for e in ec2:
        analyze.classify_ec2_idle(e)

    # 5. ALB traffic, NAT traffic, VPC endpoints
    log.info("ALB traffic ...")
    albs = analyze.alb_classify(collect.alb_traffic(lbs))
    log.info("NAT traffic ...")
    nats = analyze.nat_classify(collect.nat_traffic(nats))
    vpces = collect.vpc_endpoints(regions)

    # 6. RDS + ElastiCache + Lambda + Logs
    log.info("RDS / ElastiCache / Lambda / Logs ...")
    rds_raw = collect.collect_rds(regions)
    rds = collect.enrich_rds_metrics(rds_raw)
    for r in rds:
        v, why = analyze.rds_verdict(r)
        r["Verdict"] = v
        r["Rationale"] = why
        r["MonthlyUSD_approx"] = analyze.rds_monthly_cost(r)
    ec_raw = collect.collect_elasticache(regions)
    ec = collect.enrich_elasticache_metrics(ec_raw)
    for c in ec:
        v, why = analyze.ec_verdict(c)
        c["Verdict"] = v
        c["Rationale"] = why
        c["MonthlyUSD_approx"] = analyze.ec_monthly_cost(c)
    lambdas = collect.collect_lambda(regions)
    logs = collect.collect_log_groups(regions)

    # 7. EBS / Snapshots
    log.info("EBS volumes + Snapshot deps ...")
    volumes = collect.collect_all_volumes(regions)
    my_amis = collect.collect_my_amis(regions)
    snaps_dep = analyze.snapshot_dependency(snaps, my_amis)

    # 8. S3
    log.info("S3 buckets + sizes ...")
    buckets = collect.collect_s3_buckets()
    if os.environ.get("ENABLE_S3_LIFECYCLE", "true").lower() == "true":
        buckets = collect.bucket_sizes(buckets)
        buckets = collect.bucket_lifecycle_and_versioning(buckets)

    # 9. CloudFront / Route53
    cloudfront = collect.collect_cloudfront()
    zones = collect.collect_route53_zones()

    # 10. Compute Optimizer
    log.info("Compute Optimizer ...")
    co = collect.compute_optimizer_recs()
    co_summary = analyze.co_savings_summary(co)

    # 11. Cost Explorer + SP/RI
    log.info("Cost Explorer + SP/RI ...")
    ce_data = collect.cost_explorer_monthly()
    sp_status = collect.savings_plans_status()

    # 12. Tags
    log.info("Tag governance ...")
    tags = collect.tag_audit(regions)

    # 13. Orphans
    log.info("Orphans ...")
    orphans = collect.collect_orphans(regions)

    # ── Build report ──────────────────────────────────────────────────
    data = {
        "account": caller["Account"],
        "caller_arn": caller["Arn"],
        "regions": regions,
        "ec2": ec2,
        "ebs_unattached": ebs_unattached,
        "eip_unattached": eip_unattached,
        "albs": albs,
        "nats": nats,
        "vpces": vpces,
        "rds": rds,
        "ec": ec,
        "lambdas": lambdas,
        "logs": logs,
        "volumes": volumes,
        "snaps_dep": snaps_dep,
        "my_amis": my_amis,
        "buckets": buckets,
        "cloudfront": cloudfront,
        "zones": zones,
        "co": co,
        "co_summary": co_summary,
        "ce": ce_data,
        "sp_status": sp_status,
        "tags": tags,
        "orphans": orphans,
        "generated_at": start.isoformat(),
        "duration_seconds": (datetime.now(timezone.utc) - start).total_seconds(),
    }

    log.info("Rendering reports ...")
    paths = report.render_all(out_dir, data)
    log.info("Reports written to %s", out_dir)

    # ── Upload + notify ──────────────────────────────────────────────
    bucket = os.environ.get("S3_REPORT_BUCKET")
    if bucket:
        s3_prefix = today
        s3_uri = notify.upload_to_s3(out_dir, bucket, s3_prefix)
    else:
        s3_uri = f"file://{out_dir}"
        log.warning("S3_REPORT_BUCKET not set — skipping S3 upload")

    summary = notify.build_summary(data, s3_uri)
    log.info("Summary:\n%s", summary["text"])

    sns_arn = os.environ.get("SNS_TOPIC_ARN")
    if sns_arn:
        notify.publish_to_sns(sns_arn, summary["subject"], summary["text"])

    slack_url = os.environ.get("SLACK_WEBHOOK_URL")
    if slack_url:
        try:
            notify.post_to_slack(slack_url, summary["text"])
        except Exception as e:
            log.warning("Slack post failed: %s", e)

    log.info("==== Done in %.1fs ====", data["duration_seconds"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
