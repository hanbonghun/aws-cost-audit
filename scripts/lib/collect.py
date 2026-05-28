"""
Data collection for the 17 cost investigations.

Pure read-only — never calls Create/Modify/Delete/Put. boto3 client
calls are limited to describe_*/list_*/get_* methods.
"""
from __future__ import annotations

import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

BOTO_CFG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"},
    max_pool_connections=50,
)

NOW = dt.datetime.now(dt.timezone.utc)
WINDOW_30D_END = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
WINDOW_30D_START = (NOW - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
WINDOW_3D_END = WINDOW_30D_END
WINDOW_3D_START = (NOW - dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
SNAP_CUTOFF = (NOW - dt.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")


def session(region: Optional[str] = None) -> boto3.Session:
    return boto3.Session(region_name=region)


def opted_in_regions() -> list[str]:
    """Return all opted-in EC2 regions."""
    ec2 = session().client("ec2", config=BOTO_CFG)
    resp = ec2.describe_regions()
    return [
        r["RegionName"]
        for r in resp["Regions"]
        if r.get("OptInStatus") != "not-opted-in"
    ]


def caller_identity() -> dict:
    sts = session().client("sts", config=BOTO_CFG)
    return sts.get_caller_identity()


def _paginate(client, method: str, key: str, **kwargs) -> list[dict]:
    """Helper: paginate a boto3 client method and collect results."""
    paginator = client.get_paginator(method)
    out: list[dict] = []
    for page in paginator.paginate(**kwargs):
        out.extend(page.get(key, []) or [])
    return out


def _parallel_regions(fn, regions: list[str], max_workers: int = 17) -> list:
    """Run fn(region) concurrently across regions; flatten list results."""
    out: list = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fn, r): r for r in regions}
        for f in as_completed(futures):
            try:
                v = f.result()
                if isinstance(v, list):
                    out.extend(v)
                elif v is not None:
                    out.append(v)
            except ClientError as e:
                log.warning("region %s failed: %s", futures[f], e)
    return out


# ──────────────────────────────────────────────────────────────────────
# Inv 1-4 (network) & inventories
# ──────────────────────────────────────────────────────────────────────

def collect_unattached_ebs(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        ec2 = session(region).client("ec2", config=BOTO_CFG)
        vols = _paginate(
            ec2, "describe_volumes", "Volumes",
            Filters=[{"Name": "status", "Values": ["available"]}],
        )
        return [
            {
                "Region": region,
                "VolumeId": v["VolumeId"],
                "Size": v["Size"],
                "Type": v["VolumeType"],
                "AZ": v["AvailabilityZone"],
                "Created": v["CreateTime"].isoformat(),
            }
            for v in vols
        ]
    return _parallel_regions(per_region, regions)


def collect_unattached_eips(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        ec2 = session(region).client("ec2", config=BOTO_CFG)
        resp = ec2.describe_addresses()
        return [
            {
                "Region": region,
                "PublicIp": a.get("PublicIp"),
                "AllocationId": a.get("AllocationId"),
                "Domain": a.get("Domain"),
            }
            for a in resp.get("Addresses", [])
            if not a.get("AssociationId")
        ]
    return _parallel_regions(per_region, regions)


def collect_old_snapshots(regions: list[str]) -> list[dict]:
    cutoff = NOW - dt.timedelta(days=90)
    def per_region(region: str) -> list[dict]:
        ec2 = session(region).client("ec2", config=BOTO_CFG)
        snaps = _paginate(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"])
        return [
            {
                "Region": region,
                "SnapshotId": s["SnapshotId"],
                "Size": s["VolumeSize"],
                "Started": s["StartTime"].isoformat(),
                "VolumeId": s.get("VolumeId"),
                "Description": (s.get("Description") or "")[:200],
            }
            for s in snaps
            if s["StartTime"].replace(tzinfo=dt.timezone.utc) < cutoff
        ]
    return _parallel_regions(per_region, regions)


def collect_nat_gateways(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        ec2 = session(region).client("ec2", config=BOTO_CFG)
        ngs = _paginate(
            ec2, "describe_nat_gateways", "NatGateways",
            Filter=[{"Name": "state", "Values": ["available"]}],
        )
        return [
            {
                "Region": region,
                "NatGatewayId": n["NatGatewayId"],
                "VpcId": n["VpcId"],
                "SubnetId": n["SubnetId"],
                "Created": n["CreateTime"].isoformat(),
            }
            for n in ngs
        ]
    return _parallel_regions(per_region, regions)


def collect_load_balancers(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        v2 = session(region).client("elbv2", config=BOTO_CFG)
        classic = session(region).client("elb", config=BOTO_CFG)
        out: list[dict] = []
        try:
            for lb in _paginate(v2, "describe_load_balancers", "LoadBalancers"):
                out.append({
                    "Region": region,
                    "Arn": lb["LoadBalancerArn"],
                    "Name": lb["LoadBalancerName"],
                    "Type": lb["Type"],
                    "Scheme": lb["Scheme"],
                    "Created": lb["CreatedTime"].isoformat(),
                    "State": lb["State"]["Code"],
                    "DNS": lb["DNSName"],
                    "Family": "v2",
                })
        except ClientError as e:
            log.warning("elbv2 %s failed: %s", region, e)
        try:
            for lb in _paginate(classic, "describe_load_balancers", "LoadBalancerDescriptions"):
                out.append({
                    "Region": region,
                    "Name": lb["LoadBalancerName"],
                    "Type": "classic",
                    "Scheme": lb.get("Scheme"),
                    "Created": lb["CreatedTime"].isoformat(),
                    "DNS": lb.get("DNSName"),
                    "Family": "classic",
                })
        except ClientError as e:
            log.warning("elb classic %s failed: %s", region, e)
        return out
    return _parallel_regions(per_region, regions)


# ──────────────────────────────────────────────────────────────────────
# EC2 instances + 30d CPU
# ──────────────────────────────────────────────────────────────────────

def collect_running_ec2(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        ec2 = session(region).client("ec2", config=BOTO_CFG)
        out: list[dict] = []
        for reservation in _paginate(
            ec2, "describe_instances", "Reservations",
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}],
        ):
            for i in reservation["Instances"]:
                tags = {t["Key"]: t["Value"] for t in (i.get("Tags") or [])}
                out.append({
                    "Region": region,
                    "Id": i["InstanceId"],
                    "Type": i["InstanceType"],
                    "LaunchTime": i["LaunchTime"].isoformat(),
                    "Name": tags.get("Name", "-"),
                    "PublicIp": i.get("PublicIpAddress"),
                    "PrivateIp": i.get("PrivateIpAddress"),
                    "VpcId": i.get("VpcId"),
                    "SubnetId": i.get("SubnetId"),
                    "Tags": tags,
                    "BlockDevices": [
                        bdm["Ebs"]["VolumeId"]
                        for bdm in i.get("BlockDeviceMappings", [])
                        if "Ebs" in bdm
                    ],
                })
        return out
    return _parallel_regions(per_region, regions)


def cw_metric_avg(region: str, namespace: str, metric: str,
                  dims: list[dict], days: int = 30,
                  stats: tuple[str, ...] = ("Average", "Maximum")) -> dict:
    cw = session(region).client("cloudwatch", config=BOTO_CFG)
    end = NOW
    start = end - dt.timedelta(days=days)
    resp = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric,
        Dimensions=dims,
        StartTime=start,
        EndTime=end,
        Period=86400,
        Statistics=list(stats),
    )
    dps = resp.get("Datapoints", [])
    if not dps:
        return {"avg": None, "max": None, "days": 0}
    return {
        "avg": sum(d["Average"] for d in dps if "Average" in d) / len(dps) if "Average" in stats else None,
        "max": max(d.get("Maximum", d.get("Average", 0)) for d in dps) if "Maximum" in stats else None,
        "sum": sum(d["Sum"] for d in dps if "Sum" in d) if "Sum" in stats else None,
        "days": len(dps),
    }


def enrich_ec2_cpu(ec2: list[dict]) -> list[dict]:
    """Add 30-day CPU avg/max to each running instance."""
    def fetch(e: dict) -> dict:
        m = cw_metric_avg(
            e["Region"], "AWS/EC2", "CPUUtilization",
            [{"Name": "InstanceId", "Value": e["Id"]}],
        )
        e["AvgCPU"] = m["avg"]
        e["MaxCPU"] = m["max"]
        e["MetricDays"] = m["days"]
        return e
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(fetch, ec2))


def enrich_ec2_network(ec2: list[dict]) -> list[dict]:
    def fetch(e: dict) -> dict:
        in_m = cw_metric_avg(
            e["Region"], "AWS/EC2", "NetworkIn",
            [{"Name": "InstanceId", "Value": e["Id"]}],
            stats=("Average", "Sum"),
        )
        out_m = cw_metric_avg(
            e["Region"], "AWS/EC2", "NetworkOut",
            [{"Name": "InstanceId", "Value": e["Id"]}],
            stats=("Average", "Sum"),
        )
        e["NetIn30dGiB"] = round((in_m.get("sum") or 0) / 1024**3, 3)
        e["NetOut30dGiB"] = round((out_m.get("sum") or 0) / 1024**3, 3)
        return e
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(fetch, ec2))


# ──────────────────────────────────────────────────────────────────────
# Inv 1: ALB request volume
# ──────────────────────────────────────────────────────────────────────

def alb_traffic(lbs: list[dict]) -> list[dict]:
    """For each LB (Type=application), fetch 30d RequestCount + 5xx."""
    albs = [lb for lb in lbs if lb.get("Type") == "application"]
    def fetch(lb: dict) -> dict:
        dim_value = lb["Arn"].split("loadbalancer/", 1)[-1] if lb.get("Arn") else None
        if not dim_value:
            return lb
        req = cw_metric_avg(
            lb["Region"], "AWS/ApplicationELB", "RequestCount",
            [{"Name": "LoadBalancer", "Value": dim_value}],
            stats=("Sum",),
        )
        err = cw_metric_avg(
            lb["Region"], "AWS/ApplicationELB", "HTTPCode_Target_5XX_Count",
            [{"Name": "LoadBalancer", "Value": dim_value}],
            stats=("Sum",),
        )
        return {
            **lb,
            "Req30dTotal": int(req.get("sum") or 0),
            "ReqAvgDaily": int((req.get("sum") or 0) / max(req.get("days") or 1, 1)),
            "Errors5xx30d": int(err.get("sum") or 0),
        }
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(fetch, albs))


# ──────────────────────────────────────────────────────────────────────
# Inv 4: NAT byte usage
# ──────────────────────────────────────────────────────────────────────

def nat_traffic(nats: list[dict]) -> list[dict]:
    def fetch(n: dict) -> dict:
        bytes_m = cw_metric_avg(
            n["Region"], "AWS/NATGateway", "BytesOutToDestination",
            [{"Name": "NatGatewayId", "Value": n["NatGatewayId"]}],
            stats=("Sum",),
        )
        bytes_total = bytes_m.get("sum") or 0
        return {
            **n,
            "Bytes30d": int(bytes_total),
            "GiB30d": round(bytes_total / 1024**3, 2),
        }
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(fetch, nats))


def vpc_endpoints(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        ec2 = session(region).client("ec2", config=BOTO_CFG)
        eps = _paginate(ec2, "describe_vpc_endpoints", "VpcEndpoints")
        return [
            {
                "Region": region,
                "Id": e["VpcEndpointId"],
                "VpcId": e["VpcId"],
                "Service": e["ServiceName"],
                "Type": e["VpcEndpointType"],
                "State": e["State"],
            }
            for e in eps
        ]
    return _parallel_regions(per_region, regions)


# ──────────────────────────────────────────────────────────────────────
# Inv 5: RDS
# ──────────────────────────────────────────────────────────────────────

def collect_rds(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        rds = session(region).client("rds", config=BOTO_CFG)
        try:
            instances = _paginate(rds, "describe_db_instances", "DBInstances")
        except ClientError:
            return []
        return [
            {
                "Region": region,
                "Id": i["DBInstanceIdentifier"],
                "Class": i["DBInstanceClass"],
                "Engine": i["Engine"],
                "Status": i["DBInstanceStatus"],
                "MultiAZ": i["MultiAZ"],
                "Storage": i.get("AllocatedStorage"),
                "StorageType": i.get("StorageType"),
                "Created": i["InstanceCreateTime"].isoformat() if i.get("InstanceCreateTime") else None,
                "BackupRet": i.get("BackupRetentionPeriod"),
                "DeletionProt": i.get("DeletionProtection"),
                "PubliclyAcc": i.get("PubliclyAccessible"),
            }
            for i in instances
        ]
    return _parallel_regions(per_region, regions)


def enrich_rds_metrics(rds: list[dict]) -> list[dict]:
    def fetch(r: dict) -> dict:
        dims = [{"Name": "DBInstanceIdentifier", "Value": r["Id"]}]
        cpu = cw_metric_avg(r["Region"], "AWS/RDS", "CPUUtilization", dims)
        conn = cw_metric_avg(r["Region"], "AWS/RDS", "DatabaseConnections", dims)
        free_storage = cw_metric_avg(
            r["Region"], "AWS/RDS", "FreeStorageSpace", dims, stats=("Minimum",),
        )
        return {
            **r,
            "CPU_avg": round(cpu["avg"], 2) if cpu["avg"] is not None else None,
            "CPU_max": round(cpu["max"], 2) if cpu["max"] is not None else None,
            "Conn_avg": round(conn["avg"], 2) if conn["avg"] is not None else None,
            "Conn_max": round(conn["max"], 2) if conn["max"] is not None else None,
        }
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(fetch, rds))


# ──────────────────────────────────────────────────────────────────────
# Inv 6: ElastiCache
# ──────────────────────────────────────────────────────────────────────

def collect_elasticache(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        ec = session(region).client("elasticache", config=BOTO_CFG)
        try:
            clusters = _paginate(
                ec, "describe_cache_clusters", "CacheClusters",
                ShowCacheNodeInfo=True,
            )
        except ClientError:
            return []
        return [
            {
                "Region": region,
                "Id": c["CacheClusterId"],
                "Engine": c["Engine"],
                "Type": c["CacheNodeType"],
                "Status": c["CacheClusterStatus"],
                "NumNodes": c["NumCacheNodes"],
                "Created": c["CacheClusterCreateTime"].isoformat() if c.get("CacheClusterCreateTime") else None,
            }
            for c in clusters
        ]
    return _parallel_regions(per_region, regions)


def enrich_elasticache_metrics(ec: list[dict]) -> list[dict]:
    def fetch(c: dict) -> dict:
        dims = [{"Name": "CacheClusterId", "Value": c["Id"]}]
        cpu = cw_metric_avg(c["Region"], "AWS/ElastiCache", "CPUUtilization", dims)
        conn = cw_metric_avg(c["Region"], "AWS/ElastiCache", "CurrConnections", dims)
        mem = cw_metric_avg(
            c["Region"], "AWS/ElastiCache", "DatabaseMemoryUsagePercentage", dims,
        )
        return {
            **c,
            "CPU_avg": round(cpu["avg"], 2) if cpu["avg"] is not None else None,
            "Conn_avg": round(conn["avg"], 1) if conn["avg"] is not None else None,
            "Mem_avg_pct": round(mem["avg"], 2) if mem["avg"] is not None else None,
        }
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(fetch, ec))


# ──────────────────────────────────────────────────────────────────────
# Inv 7-8: EBS / Snapshot dependencies
# ──────────────────────────────────────────────────────────────────────

def collect_all_volumes(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        ec2 = session(region).client("ec2", config=BOTO_CFG)
        vols = _paginate(ec2, "describe_volumes", "Volumes")
        return [
            {
                "Region": region,
                "Id": v["VolumeId"],
                "Size": v["Size"],
                "Type": v["VolumeType"],
                "Iops": v.get("Iops"),
                "Throughput": v.get("Throughput"),
                "State": v["State"],
                "Attachments": [a["InstanceId"] for a in (v.get("Attachments") or [])],
            }
            for v in vols
        ]
    return _parallel_regions(per_region, regions)


def collect_my_amis(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        ec2 = session(region).client("ec2", config=BOTO_CFG)
        try:
            resp = ec2.describe_images(Owners=["self"])
        except ClientError:
            return []
        out: list[dict] = []
        for img in resp.get("Images", []):
            snaps = [
                bdm["Ebs"]["SnapshotId"]
                for bdm in img.get("BlockDeviceMappings", [])
                if bdm.get("Ebs", {}).get("SnapshotId")
            ]
            out.append({
                "Region": region,
                "ImageId": img["ImageId"],
                "Name": img.get("Name"),
                "Created": img.get("CreationDate"),
                "State": img.get("State"),
                "Snapshots": snaps,
            })
        return out
    return _parallel_regions(per_region, regions)


# ──────────────────────────────────────────────────────────────────────
# Inv 9: Lambda
# ──────────────────────────────────────────────────────────────────────

def collect_lambda(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        lam = session(region).client("lambda", config=BOTO_CFG)
        try:
            fns = _paginate(lam, "list_functions", "Functions")
        except ClientError:
            return []
        return [
            {
                "Region": region,
                "Name": f["FunctionName"],
                "Runtime": f.get("Runtime"),
                "Memory": f["MemorySize"],
                "Timeout": f["Timeout"],
                "Modified": f.get("LastModified"),
                "CodeSize": f["CodeSize"],
            }
            for f in fns
        ]
    return _parallel_regions(per_region, regions)


# ──────────────────────────────────────────────────────────────────────
# Inv 10: CloudWatch Logs
# ──────────────────────────────────────────────────────────────────────

def collect_log_groups(regions: list[str]) -> list[dict]:
    def per_region(region: str) -> list[dict]:
        logs = session(region).client("logs", config=BOTO_CFG)
        try:
            groups = _paginate(logs, "describe_log_groups", "logGroups")
        except ClientError:
            return []
        return [
            {
                "Region": region,
                "Name": g["logGroupName"],
                "Retention": g.get("retentionInDays"),
                "Bytes": g.get("storedBytes", 0),
                "Created": g.get("creationTime"),
            }
            for g in groups
        ]
    return _parallel_regions(per_region, regions)


# ──────────────────────────────────────────────────────────────────────
# Inv 11: S3
# ──────────────────────────────────────────────────────────────────────

def collect_s3_buckets() -> list[dict]:
    s3 = session().client("s3", config=BOTO_CFG)
    resp = s3.list_buckets()
    return [{"Name": b["Name"], "Created": b["CreationDate"].isoformat()}
            for b in resp.get("Buckets", [])]


def bucket_location(bucket: str) -> str:
    s3 = session().client("s3", config=BOTO_CFG)
    try:
        resp = s3.get_bucket_location(Bucket=bucket)
        loc = resp.get("LocationConstraint")
    except ClientError as e:
        log.warning("get_bucket_location(%s) failed: %s", bucket, e)
        return "us-east-1"
    if loc is None or loc == "":
        return "us-east-1"
    if loc == "EU":
        return "eu-west-1"
    return loc


STORAGE_TYPES = (
    "StandardStorage", "StandardIAStorage",
    "IntelligentTieringFAStorage", "IntelligentTieringIAStorage",
    "IntelligentTieringAAStorage", "IntelligentTieringDAAStorage",
    "IntelligentTieringAIAStorage", "OneZoneIAStorage",
    "GlacierStorage", "GlacierIRStorage", "DeepArchiveStorage",
)


def bucket_sizes(buckets: list[dict]) -> list[dict]:
    """Fetch BucketSizeBytes from CloudWatch (cheap)."""
    def fetch(b: dict) -> dict:
        region = b.get("Region") or bucket_location(b["Name"])
        b["Region"] = region
        cw = session(region).client("cloudwatch", config=BOTO_CFG)
        total = 0
        breakdown: dict[str, int] = {}
        end = NOW
        start = end - dt.timedelta(days=3)
        for st in STORAGE_TYPES:
            try:
                resp = cw.get_metric_statistics(
                    Namespace="AWS/S3",
                    MetricName="BucketSizeBytes",
                    Dimensions=[
                        {"Name": "BucketName", "Value": b["Name"]},
                        {"Name": "StorageType", "Value": st},
                    ],
                    StartTime=start,
                    EndTime=end,
                    Period=86400,
                    Statistics=["Average"],
                )
                dps = resp.get("Datapoints", [])
                if dps:
                    latest = sorted(dps, key=lambda d: d["Timestamp"])[-1]["Average"]
                    breakdown[st] = int(latest)
                    total += int(latest)
            except ClientError:
                continue
        try:
            resp = cw.get_metric_statistics(
                Namespace="AWS/S3",
                MetricName="NumberOfObjects",
                Dimensions=[
                    {"Name": "BucketName", "Value": b["Name"]},
                    {"Name": "StorageType", "Value": "AllStorageTypes"},
                ],
                StartTime=start,
                EndTime=end,
                Period=86400,
                Statistics=["Average"],
            )
            obj_dps = resp.get("Datapoints", [])
            objects = int(sorted(obj_dps, key=lambda d: d["Timestamp"])[-1]["Average"]) if obj_dps else 0
        except ClientError:
            objects = 0
        b["Bytes"] = total
        b["Objects"] = objects
        b["Breakdown"] = breakdown
        return b
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(fetch, buckets))


def bucket_lifecycle_and_versioning(buckets: list[dict]) -> list[dict]:
    s3 = session().client("s3", config=BOTO_CFG)
    def fetch(b: dict) -> dict:
        try:
            s3.get_bucket_lifecycle_configuration(Bucket=b["Name"])
            b["HasLifecycle"] = True
        except ClientError as e:
            b["HasLifecycle"] = "NoSuch" not in str(e) and "NoSuch" not in (e.response.get("Error", {}).get("Code") or "")
            if (e.response.get("Error", {}).get("Code") or "").startswith("NoSuchLifecycle"):
                b["HasLifecycle"] = False
        try:
            v = s3.get_bucket_versioning(Bucket=b["Name"])
            b["Versioning"] = v.get("Status", "Disabled")
        except ClientError:
            b["Versioning"] = "Unknown"
        return b
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(fetch, buckets))


# ──────────────────────────────────────────────────────────────────────
# Inv 12: CloudFront / Route53
# ──────────────────────────────────────────────────────────────────────

def collect_cloudfront() -> list[dict]:
    cf = session().client("cloudfront", config=BOTO_CFG)
    try:
        resp = cf.list_distributions()
    except ClientError:
        return []
    items = (resp.get("DistributionList", {}) or {}).get("Items") or []
    return [
        {
            "Id": d["Id"],
            "Domain": d["DomainName"],
            "Enabled": d["Enabled"],
            "Origin": (d.get("Origins", {}).get("Items") or [{}])[0].get("DomainName"),
            "Comment": d.get("Comment", ""),
            "Status": d["Status"],
            "Modified": d.get("LastModifiedTime").isoformat() if d.get("LastModifiedTime") else None,
            "PriceClass": d.get("PriceClass"),
        }
        for d in items
    ]


def collect_route53_zones() -> list[dict]:
    r53 = session().client("route53", config=BOTO_CFG)
    try:
        zones = _paginate(r53, "list_hosted_zones", "HostedZones")
    except ClientError:
        return []
    return [
        {
            "Id": z["Id"],
            "Name": z["Name"],
            "Records": z["ResourceRecordSetCount"],
            "Private": z.get("Config", {}).get("PrivateZone", False),
        }
        for z in zones
    ]


# ──────────────────────────────────────────────────────────────────────
# Inv 13: Compute Optimizer
# ──────────────────────────────────────────────────────────────────────

def compute_optimizer_recs() -> dict:
    """Returns dict with status + 4 categories of recommendations."""
    co = session().client("compute-optimizer", config=BOTO_CFG)
    out: dict[str, Any] = {}
    try:
        out["status"] = co.get_enrollment_status()
    except ClientError as e:
        out["status"] = {"status": "Unknown", "error": str(e)}

    for method, key in (
        ("get_ec2_instance_recommendations", "instanceRecommendations"),
        ("get_ebs_volume_recommendations", "volumeRecommendations"),
        ("get_lambda_function_recommendations", "lambdaFunctionRecommendations"),
        ("get_auto_scaling_group_recommendations", "autoScalingGroupRecommendations"),
    ):
        try:
            resp = getattr(co, method)()
            out[key] = resp.get(key, []) or []
        except ClientError as e:
            log.warning("%s failed: %s", method, e)
            out[key] = []
    return out


# ──────────────────────────────────────────────────────────────────────
# Inv 14-15: Cost Explorer / SP / RI
# ──────────────────────────────────────────────────────────────────────

def cost_explorer_monthly(days: int = 90) -> dict:
    ce = session("us-east-1").client("ce", config=BOTO_CFG)
    end = NOW.date()
    start = end - dt.timedelta(days=days)
    monthly = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost", "UsageQuantity"],
    )
    by_service = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    return {"monthly": monthly, "by_service": by_service}


def savings_plans_status(days: int = 30) -> dict:
    ce = session("us-east-1").client("ce", config=BOTO_CFG)
    end = NOW.date()
    start = end - dt.timedelta(days=days)
    out: dict = {}
    try:
        out["sp_coverage"] = ce.get_savings_plans_coverage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        )
    except ClientError as e:
        out["sp_coverage_error"] = str(e)
    try:
        out["ri_coverage"] = ce.get_reservation_coverage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        )
    except ClientError as e:
        out["ri_coverage_error"] = str(e)
    try:
        out["sp_purchase"] = ce.get_savings_plans_purchase_recommendation(
            SavingsPlansType="COMPUTE_SP",
            TermInYears="ONE_YEAR",
            PaymentOption="NO_UPFRONT",
            LookbackPeriodInDays="SIXTY_DAYS",
        )
    except ClientError as e:
        out["sp_purchase_error"] = str(e)
    return out


# ──────────────────────────────────────────────────────────────────────
# Inv 16: Tags
# ──────────────────────────────────────────────────────────────────────

def tag_audit(regions: list[str]) -> dict:
    """Audit Owner/Project/Environment tag coverage."""
    required = ["Owner", "Project", "Environment"]
    required_lc = [r.lower() for r in required]
    by_type: dict[str, dict] = {}
    types = [
        "ec2:instance", "ec2:volume", "rds:db", "rds:cluster",
        "elasticloadbalancing:loadbalancer", "elasticache:cluster",
    ]
    def per_region(region: str) -> dict:
        rgt = session(region).client("resourcegroupstaggingapi", config=BOTO_CFG)
        try:
            resources = _paginate(
                rgt, "get_resources", "ResourceTagMappingList",
                ResourceTypeFilters=types,
            )
        except ClientError:
            return {}
        local: dict[str, dict] = {}
        for r in resources:
            arn = r["ResourceARN"]
            parts = arn.split(":")
            try:
                rtype = parts[2] + ":" + parts[5].split("/")[0]
            except IndexError:
                continue
            tags = {t["Key"].lower(): t["Value"] for t in (r.get("Tags") or [])}
            missing = [req for req, reqlc in zip(required, required_lc) if reqlc not in tags]
            d = local.setdefault(rtype, {
                "total": 0,
                "missing_any": 0,
                "missing": {k: 0 for k in required},
            })
            d["total"] += 1
            if missing:
                d["missing_any"] += 1
            for m in missing:
                d["missing"][m] += 1
        return local
    per_region_results = _parallel_regions(per_region, regions)
    for d in per_region_results:
        if not isinstance(d, dict):
            continue
        for rtype, summary in d.items():
            agg = by_type.setdefault(rtype, {
                "total": 0,
                "missing_any": 0,
                "missing": {k: 0 for k in required},
            })
            agg["total"] += summary["total"]
            agg["missing_any"] += summary["missing_any"]
            for k in required:
                agg["missing"][k] += summary["missing"][k]
    return by_type


# ──────────────────────────────────────────────────────────────────────
# Inv 17: Orphans
# ──────────────────────────────────────────────────────────────────────

def collect_orphans(regions: list[str]) -> dict:
    out: dict[str, list] = {
        "detached_eni": [],
        "stopped_ec2": [],
        "target_groups": [],
        "auto_scaling_groups": [],
        "launch_templates": [],
        "security_groups": [],
    }

    def per_region(region: str) -> dict:
        ec2 = session(region).client("ec2", config=BOTO_CFG)
        v2 = session(region).client("elbv2", config=BOTO_CFG)
        asg = session(region).client("autoscaling", config=BOTO_CFG)
        local: dict[str, list] = {k: [] for k in out}
        try:
            for e in _paginate(
                ec2, "describe_network_interfaces", "NetworkInterfaces",
                Filters=[{"Name": "status", "Values": ["available"]}],
            ):
                local["detached_eni"].append({
                    "Region": region,
                    "Id": e["NetworkInterfaceId"],
                    "VpcId": e.get("VpcId"),
                    "SubnetId": e.get("SubnetId"),
                })
        except ClientError as e:
            log.warning("describe_network_interfaces %s: %s", region, e)
        try:
            for r in _paginate(
                ec2, "describe_instances", "Reservations",
                Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}],
            ):
                for i in r["Instances"]:
                    tags = {t["Key"]: t["Value"] for t in (i.get("Tags") or [])}
                    local["stopped_ec2"].append({
                        "Region": region,
                        "Id": i["InstanceId"],
                        "Type": i["InstanceType"],
                        "Name": tags.get("Name", "-"),
                        "Stopped": i.get("StateTransitionReason"),
                    })
        except ClientError as e:
            log.warning("describe_instances stopped %s: %s", region, e)
        try:
            for tg in _paginate(v2, "describe_target_groups", "TargetGroups"):
                if not tg.get("LoadBalancerArns"):
                    local["target_groups"].append({
                        "Region": region,
                        "Name": tg["TargetGroupName"],
                        "Arn": tg["TargetGroupArn"],
                    })
        except ClientError:
            pass
        try:
            for g in _paginate(asg, "describe_auto_scaling_groups", "AutoScalingGroups"):
                if g["DesiredCapacity"] == 0:
                    local["auto_scaling_groups"].append({
                        "Region": region,
                        "Name": g["AutoScalingGroupName"],
                        "Desired": g["DesiredCapacity"],
                    })
        except ClientError:
            pass
        try:
            for lt in _paginate(ec2, "describe_launch_templates", "LaunchTemplates"):
                local["launch_templates"].append({
                    "Region": region,
                    "Id": lt["LaunchTemplateId"],
                    "Name": lt["LaunchTemplateName"],
                })
        except ClientError:
            pass
        return local

    results = _parallel_regions(per_region, regions)
    for r in results:
        if isinstance(r, dict):
            for k, v in r.items():
                out[k].extend(v)
    return out
