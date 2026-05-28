"""Unit tests for `scripts/lib/diff.py`. Only the pure `compute_diff`
function is covered here — the S3 fetch helpers are integration-tested
elsewhere (or manually).
"""
from __future__ import annotations

import pytest

from lib import diff


def _summary(
    *,
    account: str = "123456789012",
    generated_at: str = "2026-05-01T00:00:00+00:00",
    ec2: list | None = None,
    albs: list | None = None,
    nats: list | None = None,
    rds: list | None = None,
    snaps_dep: list | None = None,
    monthly_cost: list[float] | None = None,
) -> dict:
    """Build a minimal master_summary.json-shaped dict for tests."""
    s: dict = {
        "account": account,
        "generated_at": generated_at,
        "ec2": ec2 or [],
        "albs": albs or [],
        "nats": nats or [],
        "rds": rds or [],
        "snaps_dep": snaps_dep or [],
    }
    if monthly_cost is not None:
        s["ce"] = {
            "monthly": {
                "ResultsByTime": [
                    {"Total": {"UnblendedCost": {"Amount": str(v)}}}
                    for v in monthly_cost
                ]
            }
        }
    return s


# ──────────────────────────────────────────────────────────────────────
# EC2 idle diff
# ──────────────────────────────────────────────────────────────────────

def test_diff_ec2_newly_idle_detected():
    prev = _summary(ec2=[{"Id": "i-1", "AvgCPU": 50.0}])
    curr = _summary(ec2=[{"Id": "i-1", "AvgCPU": 1.0}])
    d = diff.compute_diff(curr, prev)
    assert d["ec2_idle"]["newly_flagged"] == ["i-1"]
    assert d["ec2_idle"]["resolved"] == []


def test_diff_ec2_resolved_detected():
    prev = _summary(ec2=[{"Id": "i-1", "AvgCPU": 1.0}])
    curr = _summary(ec2=[{"Id": "i-1", "AvgCPU": 50.0}])
    d = diff.compute_diff(curr, prev)
    assert d["ec2_idle"]["resolved"] == ["i-1"]


def test_diff_ec2_persisted_idle():
    prev = _summary(ec2=[{"Id": "i-1", "AvgCPU": 1.0}])
    curr = _summary(ec2=[{"Id": "i-1", "AvgCPU": 1.2}])
    d = diff.compute_diff(curr, prev)
    assert d["ec2_idle"]["persisted"] == ["i-1"]
    assert d["ec2_idle"]["newly_flagged"] == []


def test_diff_ec2_disjoint_instances_only_appear_on_their_side():
    prev = _summary(ec2=[{"Id": "i-old", "AvgCPU": 0.5}])
    curr = _summary(ec2=[{"Id": "i-new", "AvgCPU": 0.5}])
    d = diff.compute_diff(curr, prev)
    assert d["ec2_idle"]["newly_flagged"] == ["i-new"]
    assert d["ec2_idle"]["resolved"] == ["i-old"]


def test_diff_ec2_none_cpu_is_treated_as_idle():
    """None metrics fall through `(AvgCPU or 0) < 5` and count as idle —
    same convention as the rest of the codebase. An instance whose CPU
    drops to None in the current run is still considered idle (persisted)."""
    prev = _summary(ec2=[{"Id": "i-1", "AvgCPU": 1.0}])
    curr = _summary(ec2=[{"Id": "i-1", "AvgCPU": None}])
    d = diff.compute_diff(curr, prev)
    assert d["ec2_idle"]["persisted"] == ["i-1"]
    assert d["ec2_idle"]["resolved"] == []


# ──────────────────────────────────────────────────────────────────────
# ALB zero-traffic diff
# ──────────────────────────────────────────────────────────────────────

def test_diff_alb_newly_zero_traffic():
    prev = _summary(albs=[{"Name": "alb-a", "Category": "NORMAL"}])
    curr = _summary(albs=[{"Name": "alb-a", "Category": "ZERO-TRAFFIC"}])
    d = diff.compute_diff(curr, prev)
    assert d["albs_zero_traffic"]["newly_flagged"] == ["alb-a"]


def test_diff_alb_resolved():
    prev = _summary(albs=[{"Name": "alb-a", "Category": "ZERO-TRAFFIC"}])
    curr = _summary(albs=[{"Name": "alb-a", "Category": "NORMAL"}])
    d = diff.compute_diff(curr, prev)
    assert d["albs_zero_traffic"]["resolved"] == ["alb-a"]


def test_diff_alb_low_traffic_not_counted_as_zero():
    prev = _summary(albs=[{"Name": "alb-a", "Category": "LOW-TRAFFIC"}])
    curr = _summary(albs=[{"Name": "alb-a", "Category": "LOW-TRAFFIC"}])
    d = diff.compute_diff(curr, prev)
    assert d["albs_zero_traffic"]["persisted"] == []


# ──────────────────────────────────────────────────────────────────────
# NAT zero-traffic diff
# ──────────────────────────────────────────────────────────────────────

def test_diff_nat_newly_flagged():
    prev = _summary(nats=[{"NatGatewayId": "nat-1", "Category": "LOW"}])
    curr = _summary(nats=[{"NatGatewayId": "nat-1", "Category": "ZERO-TRAFFIC"}])
    d = diff.compute_diff(curr, prev)
    assert d["nats_zero_traffic"]["newly_flagged"] == ["nat-1"]


def test_diff_nat_resolved():
    prev = _summary(nats=[{"NatGatewayId": "nat-1", "Category": "ZERO-TRAFFIC"}])
    curr = _summary(nats=[{"NatGatewayId": "nat-1", "Category": "LOW"}])
    d = diff.compute_diff(curr, prev)
    assert d["nats_zero_traffic"]["resolved"] == ["nat-1"]


# ──────────────────────────────────────────────────────────────────────
# RDS idle diff
# ──────────────────────────────────────────────────────────────────────

def test_diff_rds_newly_idle():
    prev = _summary(rds=[{"Id": "db-1", "Verdict": "OK"}])
    curr = _summary(rds=[{"Id": "db-1", "Verdict": "IDLE"}])
    d = diff.compute_diff(curr, prev)
    assert d["rds_idle"]["newly_flagged"] == ["db-1"]


def test_diff_rds_downsize_is_not_idle():
    prev = _summary(rds=[{"Id": "db-1", "Verdict": "OK"}])
    curr = _summary(rds=[{"Id": "db-1", "Verdict": "DOWNSIZE"}])
    d = diff.compute_diff(curr, prev)
    assert d["rds_idle"]["newly_flagged"] == []


# ──────────────────────────────────────────────────────────────────────
# Snapshot diff
# ──────────────────────────────────────────────────────────────────────

def test_diff_snapshot_freshly_unbound_is_newly_flagged():
    prev = _summary(snaps_dep=[{"SnapshotId": "snap-1", "BoundAMIs": [{"AMI": "ami-1"}]}])
    curr = _summary(snaps_dep=[{"SnapshotId": "snap-1", "BoundAMIs": []}])
    d = diff.compute_diff(curr, prev)
    assert d["free_snapshots"]["newly_flagged"] == ["snap-1"]


def test_diff_snapshot_resolved_when_deleted_or_rebound():
    prev = _summary(snaps_dep=[{"SnapshotId": "snap-1", "BoundAMIs": []}])
    curr = _summary(snaps_dep=[])
    d = diff.compute_diff(curr, prev)
    assert d["free_snapshots"]["resolved"] == ["snap-1"]


# ──────────────────────────────────────────────────────────────────────
# Cost delta
# ──────────────────────────────────────────────────────────────────────

def test_diff_cost_delta_increase():
    """The second-to-last entry in monthly is the "last completed month"."""
    prev = _summary(monthly_cost=[1000.0, 1100.0, 50.0])
    curr = _summary(monthly_cost=[1100.0, 1200.0, 60.0])
    d = diff.compute_diff(curr, prev)
    assert d["cost"]["previous"] == pytest.approx(1100.0)
    assert d["cost"]["current"] == pytest.approx(1200.0)
    assert d["cost"]["delta_usd"] == pytest.approx(100.0)
    assert d["cost"]["delta_pct"] == pytest.approx(100.0 / 1100.0 * 100)


def test_diff_cost_delta_decrease():
    prev = _summary(monthly_cost=[1000.0, 1200.0, 50.0])
    curr = _summary(monthly_cost=[1100.0, 900.0, 40.0])
    d = diff.compute_diff(curr, prev)
    assert d["cost"]["delta_usd"] == pytest.approx(-300.0)
    assert d["cost"]["delta_pct"] == pytest.approx(-25.0)


def test_diff_cost_missing_data_returns_none_delta():
    d = diff.compute_diff(_summary(), _summary())
    assert d["cost"]["current"] is None
    assert d["cost"]["previous"] is None
    assert d["cost"]["delta_usd"] is None


def test_diff_cost_handles_only_one_month_each():
    """When only one ResultsByTime entry exists, use it (no -2 index)."""
    prev = _summary(monthly_cost=[500.0])
    curr = _summary(monthly_cost=[800.0])
    d = diff.compute_diff(curr, prev)
    assert d["cost"]["previous"] == pytest.approx(500.0)
    assert d["cost"]["current"] == pytest.approx(800.0)


def test_diff_cost_zero_previous_avoids_divide_by_zero():
    """When `previous` is 0.0, `delta_pct` is None (not a ZeroDivisionError)."""
    prev = _summary(monthly_cost=[1.0, 0.0, 200.0])    # last completed = index -2 = 0.0
    curr = _summary(monthly_cost=[100.0, 50.0, 300.0])  # last completed = 50.0
    d = diff.compute_diff(curr, prev)
    assert d["cost"]["previous"] == pytest.approx(0.0)
    assert d["cost"]["current"] == pytest.approx(50.0)
    assert d["cost"]["delta_usd"] == pytest.approx(50.0)
    assert d["cost"]["delta_pct"] is None


# ──────────────────────────────────────────────────────────────────────
# Top-level shape
# ──────────────────────────────────────────────────────────────────────

def test_diff_previous_date_extracted_from_generated_at():
    prev = _summary(generated_at="2026-04-15T12:00:00+00:00")
    curr = _summary()
    d = diff.compute_diff(curr, prev)
    assert d["previous_date"] == "2026-04-15"


def test_diff_with_completely_empty_inputs_returns_well_formed():
    d = diff.compute_diff({}, {})
    for k in ("ec2_idle", "albs_zero_traffic", "nats_zero_traffic",
              "rds_idle", "free_snapshots"):
        assert d[k]["newly_flagged"] == []
        assert d[k]["resolved"] == []
    assert d["cost"]["current"] is None
