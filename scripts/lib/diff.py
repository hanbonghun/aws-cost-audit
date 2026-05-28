"""
Month-over-month diff between two master_summary.json snapshots.

The diff itself is computed by a pure function (`compute_diff`) — no AWS calls
in the comparison. Two thin helpers read the previous run from the report S3
bucket using the same read-only access already granted by the inline policy
(`s3:ListBucket`, `s3:GetObject`).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

BOTO_CFG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})/?$")


def find_previous_run(bucket: str, current_date: str) -> Optional[tuple[str, str]]:
    """Return (date, S3 key) of the most recent prior `YYYY-MM-DD/data/master_summary.json`.

    Returns None if no prior run is found or if listing fails.
    """
    s3 = boto3.client("s3", config=BOTO_CFG)
    found: list[tuple[str, str]] = []
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
            for prefix in page.get("CommonPrefixes") or []:
                p = (prefix.get("Prefix") or "").rstrip("/")
                m = DATE_PREFIX_RE.match(p + "/")
                if not m:
                    continue
                date = m.group(1)
                if date < current_date:
                    found.append((date, f"{date}/data/master_summary.json"))
    except ClientError as e:
        log.warning("list previous runs failed: %s", e)
        return None
    if not found:
        return None
    found.sort(reverse=True)
    return found[0]


def load_previous_summary(bucket: str, key: str) -> Optional[dict]:
    s3 = boto3.client("s3", config=BOTO_CFG)
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())
    except ClientError as e:
        log.warning("load previous summary %s failed: %s", key, e)
        return None
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("parse previous summary %s failed: %s", key, e)
        return None


def _idle_ec2_ids(summary: dict) -> set[str]:
    return {
        e["Id"]
        for e in (summary.get("ec2") or [])
        if isinstance(e, dict) and e.get("Id") and (e.get("AvgCPU") or 0) < 5
    }


def _verdict_set(items, id_key: str, *verdicts: str) -> set[str]:
    return {
        i[id_key]
        for i in (items or [])
        if isinstance(i, dict) and i.get(id_key) and i.get("Verdict") in verdicts
    }


def _category_set(items, id_key: str, *categories: str) -> set[str]:
    return {
        i[id_key]
        for i in (items or [])
        if isinstance(i, dict) and i.get(id_key) and i.get("Category") in categories
    }


def _free_snapshot_ids(summary: dict) -> set[str]:
    return {
        s["SnapshotId"]
        for s in (summary.get("snaps_dep") or [])
        if isinstance(s, dict) and s.get("SnapshotId") and not s.get("BoundAMIs")
    }


def _last_completed_month_cost(summary: dict) -> Optional[float]:
    results = (summary.get("ce") or {}).get("monthly", {}).get("ResultsByTime") or []
    if not results:
        return None
    last = results[-2] if len(results) >= 2 else results[-1]
    try:
        return float(last["Total"]["UnblendedCost"]["Amount"])
    except (KeyError, TypeError, ValueError):
        return None


def compute_diff(current: dict, previous: dict) -> dict:
    """Pure diff between two master_summary.json structures.

    The output schema is stable; report.py consumes these fields by name.
    Sets are returned as sorted lists for deterministic rendering.
    """
    cur_idle, prev_idle = _idle_ec2_ids(current), _idle_ec2_ids(previous)
    cur_zalb = _category_set(current.get("albs"), "Name", "ZERO-TRAFFIC")
    prev_zalb = _category_set(previous.get("albs"), "Name", "ZERO-TRAFFIC")
    cur_znat = _category_set(current.get("nats"), "NatGatewayId", "ZERO-TRAFFIC")
    prev_znat = _category_set(previous.get("nats"), "NatGatewayId", "ZERO-TRAFFIC")
    cur_irds = _verdict_set(current.get("rds"), "Id", "IDLE")
    prev_irds = _verdict_set(previous.get("rds"), "Id", "IDLE")
    cur_freesnap = _free_snapshot_ids(current)
    prev_freesnap = _free_snapshot_ids(previous)

    cur_cost = _last_completed_month_cost(current)
    prev_cost = _last_completed_month_cost(previous)
    delta_usd = (
        cur_cost - prev_cost
        if cur_cost is not None and prev_cost is not None
        else None
    )
    delta_pct = (
        (cur_cost - prev_cost) / prev_cost * 100
        if cur_cost is not None and prev_cost not in (None, 0)
        else None
    )

    def _sets(cur: set[str], prev: set[str]) -> dict:
        return {
            "newly_flagged": sorted(cur - prev),
            "resolved": sorted(prev - cur),
            "persisted": sorted(cur & prev),
        }

    return {
        "previous_date": (previous.get("generated_at") or "")[:10] or None,
        "previous_account": previous.get("account"),
        "ec2_idle": _sets(cur_idle, prev_idle),
        "albs_zero_traffic": _sets(cur_zalb, prev_zalb),
        "nats_zero_traffic": _sets(cur_znat, prev_znat),
        "rds_idle": _sets(cur_irds, prev_irds),
        "free_snapshots": _sets(cur_freesnap, prev_freesnap),
        "cost": {
            "current": cur_cost,
            "previous": prev_cost,
            "delta_usd": delta_usd,
            "delta_pct": delta_pct,
        },
    }
