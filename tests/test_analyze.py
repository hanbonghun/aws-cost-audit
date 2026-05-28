"""Unit tests for the pure verdict / classification / pricing functions in
`scripts/lib/analyze.py`. These tests do not touch AWS.
"""
from __future__ import annotations

import pytest

from lib import analyze


# ──────────────────────────────────────────────────────────────────────
# classify_ec2_idle
# ──────────────────────────────────────────────────────────────────────

def _ec2(name="web", avg=0.0, mx=0.0, net_in=0.0, net_out=0.0, tg=None):
    return {
        "Name": name,
        "AvgCPU": avg,
        "MaxCPU": mx,
        "NetIn30dGiB": net_in,
        "NetOut30dGiB": net_out,
        "TargetGroupMemberships": tg or [],
    }


def test_classify_ec2_bastion_name_overrides_metrics():
    e = _ec2(name="prod-bastion-1", avg=80.0, mx=99.0)
    out = analyze.classify_ec2_idle(e)
    assert out["Verdict"] == "KEEP-BASTION"


def test_classify_ec2_jump_host_also_treated_as_bastion():
    e = _ec2(name="dev-jump-server")
    out = analyze.classify_ec2_idle(e)
    assert out["Verdict"] == "KEEP-BASTION"


def test_classify_ec2_lb_attached_zero_traffic_is_investigate():
    e = _ec2(name="app", avg=0.5, mx=5.0, net_in=0, net_out=0, tg=["tg-1"])
    out = analyze.classify_ec2_idle(e)
    assert out["Verdict"] == "INVESTIGATE-LB"


def test_classify_ec2_terminate_candidate_no_lb():
    e = _ec2(name="orphan", avg=0.2, mx=5.0, net_in=0.1, net_out=0.1)
    out = analyze.classify_ec2_idle(e)
    assert out["Verdict"] == "TERMINATE-CANDIDATE"


def test_classify_ec2_terminate_blocked_by_lb_membership():
    e = _ec2(name="orphan", avg=0.2, mx=5.0, net_in=0.1, net_out=0.1, tg=["tg-1"])
    out = analyze.classify_ec2_idle(e)
    assert out["Verdict"] != "TERMINATE-CANDIDATE"


def test_classify_ec2_downsize_low_usage():
    e = _ec2(name="app", avg=1.5, mx=15.0, net_in=5.0, net_out=5.0)
    out = analyze.classify_ec2_idle(e)
    assert out["Verdict"] == "DOWNSIZE"


def test_classify_ec2_lb_attached_with_traffic_is_investigate():
    e = _ec2(name="app", avg=3.0, mx=30.0, net_in=10.0, net_out=10.0, tg=["tg-1"])
    out = analyze.classify_ec2_idle(e)
    assert out["Verdict"] == "INVESTIGATE-LB"


def test_classify_ec2_review_when_nothing_matches():
    e = _ec2(name="app", avg=10.0, mx=50.0, net_in=5.0, net_out=5.0)
    out = analyze.classify_ec2_idle(e)
    assert out["Verdict"] == "REVIEW"


def test_classify_ec2_handles_none_metrics():
    e = {"Name": "app", "AvgCPU": None, "MaxCPU": None,
         "NetIn30dGiB": None, "NetOut30dGiB": None}
    out = analyze.classify_ec2_idle(e)
    assert "Verdict" in out
    assert "Rationale" in out


def test_classify_ec2_rationale_contains_metrics():
    e = _ec2(name="app", avg=1.5, mx=15.0)
    out = analyze.classify_ec2_idle(e)
    assert "1.50" in out["Rationale"]
    assert "15.00" in out["Rationale"]


# ──────────────────────────────────────────────────────────────────────
# ec2_monthly_cost
# ──────────────────────────────────────────────────────────────────────

def test_ec2_cost_known_type():
    cost = analyze.ec2_monthly_cost("t3.medium", ebs_gib=0)
    assert cost == pytest.approx(0.052 * 730, abs=0.01)


def test_ec2_cost_unknown_type_returns_only_ebs():
    cost = analyze.ec2_monthly_cost("unknown.type", ebs_gib=100)
    assert cost == pytest.approx(100 * 0.0912, abs=0.01)


def test_ec2_cost_zero_ebs_is_pure_compute():
    cost = analyze.ec2_monthly_cost("t4g.micro", ebs_gib=0)
    assert cost == pytest.approx(0.0104 * 730, abs=0.01)


def test_ec2_cost_default_ebs_kwarg_is_zero():
    assert analyze.ec2_monthly_cost("t3.medium") == analyze.ec2_monthly_cost("t3.medium", ebs_gib=0)


# ──────────────────────────────────────────────────────────────────────
# rds_verdict + rds_monthly_cost
# ──────────────────────────────────────────────────────────────────────

def test_rds_verdict_idle():
    r = {"CPU_avg": 2.0, "Conn_avg": 0.5, "MultiAZ": False}
    verdict, _ = analyze.rds_verdict(r)
    assert verdict == "IDLE"


def test_rds_verdict_downsize_single_az():
    r = {"CPU_avg": 3.0, "Conn_avg": 10.0, "MultiAZ": False}
    verdict, _ = analyze.rds_verdict(r)
    assert verdict == "DOWNSIZE"


def test_rds_verdict_multiaz_low_cpu_is_not_downsize():
    r = {"CPU_avg": 3.0, "Conn_avg": 10.0, "MultiAZ": True}
    verdict, _ = analyze.rds_verdict(r)
    assert verdict == "OK"


def test_rds_verdict_ok_normal_usage():
    r = {"CPU_avg": 30.0, "Conn_avg": 100.0, "MultiAZ": False}
    verdict, _ = analyze.rds_verdict(r)
    assert verdict == "OK"


def test_rds_verdict_handles_missing_metrics_as_safe():
    r = {"CPU_avg": None, "Conn_avg": None, "MultiAZ": False}
    verdict, _ = analyze.rds_verdict(r)
    assert verdict == "OK"


def test_rds_cost_single_az():
    r = {"Class": "db.t4g.micro", "MultiAZ": False, "Storage": 20, "StorageType": "gp3"}
    cost = analyze.rds_monthly_cost(r)
    assert cost == pytest.approx(0.020 * 730 + 20 * 0.115, abs=0.01)


def test_rds_cost_multiaz_doubles():
    single = {"Class": "db.t4g.medium", "MultiAZ": False, "Storage": 100, "StorageType": "gp3"}
    multi = {"Class": "db.t4g.medium", "MultiAZ": True, "Storage": 100, "StorageType": "gp3"}
    assert analyze.rds_monthly_cost(multi) == pytest.approx(
        analyze.rds_monthly_cost(single) * 2, abs=0.01
    )


def test_rds_cost_unknown_class_returns_none():
    r = {"Class": "db.unknown.type", "MultiAZ": False, "Storage": 20, "StorageType": "gp3"}
    assert analyze.rds_monthly_cost(r) is None


def test_rds_cost_unknown_storage_type_falls_back_to_default():
    r = {"Class": "db.t4g.micro", "MultiAZ": False, "Storage": 100, "StorageType": "io2"}
    cost = analyze.rds_monthly_cost(r)
    assert cost == pytest.approx(0.020 * 730 + 100 * 0.13, abs=0.01)


# ──────────────────────────────────────────────────────────────────────
# ec_verdict + ec_monthly_cost
# ──────────────────────────────────────────────────────────────────────

def test_ec_verdict_likely_idle():
    c = {"CPU_avg": 1.0, "Conn_avg": 1.0}
    verdict, _ = analyze.ec_verdict(c)
    assert verdict == "LIKELY-IDLE"


def test_ec_verdict_ok_normal_usage():
    c = {"CPU_avg": 20.0, "Conn_avg": 50.0}
    verdict, _ = analyze.ec_verdict(c)
    assert verdict == "OK"


def test_ec_verdict_high_connections_keeps_ok():
    c = {"CPU_avg": 1.0, "Conn_avg": 100.0}
    verdict, _ = analyze.ec_verdict(c)
    assert verdict == "OK"


def test_ec_cost_known_type_multi_node():
    c = {"Type": "cache.t3.small", "NumNodes": 3}
    assert analyze.ec_monthly_cost(c) == pytest.approx(0.051 * 730 * 3, abs=0.01)


def test_ec_cost_unknown_type_returns_none():
    c = {"Type": "cache.unknown", "NumNodes": 1}
    assert analyze.ec_monthly_cost(c) is None


def test_ec_cost_missing_num_nodes_defaults_to_one():
    c = {"Type": "cache.t3.small"}
    assert analyze.ec_monthly_cost(c) == pytest.approx(0.051 * 730, abs=0.01)


# ──────────────────────────────────────────────────────────────────────
# snapshot_dependency
# ──────────────────────────────────────────────────────────────────────

def test_snapshot_dependency_bound_snapshot_is_annotated():
    snaps = [{"SnapshotId": "snap-1", "Size": 30}]
    amis = [{
        "ImageId": "ami-1", "Name": "img", "State": "available",
        "Snapshots": ["snap-1"],
    }]
    out = analyze.snapshot_dependency(snaps, amis)
    assert len(out[0]["BoundAMIs"]) == 1
    assert out[0]["BoundAMIs"][0]["AMI"] == "ami-1"


def test_snapshot_dependency_unbound_snapshot_has_empty_list():
    snaps = [{"SnapshotId": "snap-orphan", "Size": 100}]
    amis = [{"ImageId": "ami-1", "Snapshots": ["snap-different"]}]
    out = analyze.snapshot_dependency(snaps, amis)
    assert out[0]["BoundAMIs"] == []


def test_snapshot_dependency_one_snapshot_in_multiple_amis():
    snaps = [{"SnapshotId": "snap-shared", "Size": 50}]
    amis = [
        {"ImageId": "ami-a", "Snapshots": ["snap-shared"]},
        {"ImageId": "ami-b", "Snapshots": ["snap-shared"]},
    ]
    out = analyze.snapshot_dependency(snaps, amis)
    bound_ami_ids = sorted(b["AMI"] for b in out[0]["BoundAMIs"])
    assert bound_ami_ids == ["ami-a", "ami-b"]


def test_snapshot_dependency_preserves_original_fields():
    snaps = [{"SnapshotId": "snap-1", "Size": 30, "Started": "2025-01-01"}]
    amis = []
    out = analyze.snapshot_dependency(snaps, amis)
    assert out[0]["Size"] == 30
    assert out[0]["Started"] == "2025-01-01"


# ──────────────────────────────────────────────────────────────────────
# alb_classify
# ──────────────────────────────────────────────────────────────────────

def test_alb_classify_zero_traffic():
    out = analyze.alb_classify([{"Name": "a", "Req30dTotal": 0}])
    assert out[0]["Category"] == "ZERO-TRAFFIC"


def test_alb_classify_low_traffic_under_threshold():
    out = analyze.alb_classify([{"Name": "a", "Req30dTotal": 29999}])
    assert out[0]["Category"] == "LOW-TRAFFIC"


def test_alb_classify_normal_traffic_at_threshold():
    out = analyze.alb_classify([{"Name": "a", "Req30dTotal": 30000}])
    assert out[0]["Category"] == "NORMAL"


def test_alb_classify_normal_high_traffic():
    out = analyze.alb_classify([{"Name": "a", "Req30dTotal": 10_000_000}])
    assert out[0]["Category"] == "NORMAL"


def test_alb_classify_preserves_other_fields():
    out = analyze.alb_classify([{"Name": "alb-1", "Region": "us-east-1", "Req30dTotal": 0}])
    assert out[0]["Name"] == "alb-1"
    assert out[0]["Region"] == "us-east-1"


# ──────────────────────────────────────────────────────────────────────
# nat_classify
# ──────────────────────────────────────────────────────────────────────

def test_nat_classify_zero():
    out = analyze.nat_classify([{"NatGatewayId": "n", "GiB30d": 0}])
    assert out[0]["Category"] == "ZERO-TRAFFIC"


def test_nat_classify_very_low_under_1gib():
    out = analyze.nat_classify([{"NatGatewayId": "n", "GiB30d": 0.5}])
    assert out[0]["Category"] == "VERY-LOW"


def test_nat_classify_low_between_1_and_10():
    out = analyze.nat_classify([{"NatGatewayId": "n", "GiB30d": 5.0}])
    assert out[0]["Category"] == "LOW"


def test_nat_classify_normal_above_10():
    out = analyze.nat_classify([{"NatGatewayId": "n", "GiB30d": 50.0}])
    assert out[0]["Category"] == "NORMAL"


def test_nat_classify_boundary_at_1_gib_is_low():
    out = analyze.nat_classify([{"NatGatewayId": "n", "GiB30d": 1.0}])
    assert out[0]["Category"] == "LOW"


def test_nat_classify_boundary_at_10_gib_is_normal():
    out = analyze.nat_classify([{"NatGatewayId": "n", "GiB30d": 10.0}])
    assert out[0]["Category"] == "NORMAL"


# ──────────────────────────────────────────────────────────────────────
# co_savings_summary
# ──────────────────────────────────────────────────────────────────────

def test_co_summary_empty_input():
    s = analyze.co_savings_summary({})
    assert s["ec2_count"] == 0
    assert s["ec2_savings"] == 0.0
    assert s["ebs_count"] == 0
    assert s["lambda_count"] == 0
    assert s["asg_count"] == 0


def _co_rec(savings: float, key: str = "recommendationOptions") -> dict:
    return {
        key: [
            {"savingsOpportunity": {"estimatedMonthlySavings": {"value": savings}}}
        ]
    }


def test_co_summary_aggregates_ec2_and_ebs_and_lambda():
    co = {
        "instanceRecommendations": [_co_rec(10.0), _co_rec(5.5)],
        "volumeRecommendations": [_co_rec(2.0, key="volumeRecommendationOptions")],
        "lambdaFunctionRecommendations": [
            _co_rec(0.5, key="memorySizeRecommendationOptions"),
        ],
        "autoScalingGroupRecommendations": [{}, {}, {}],
    }
    s = analyze.co_savings_summary(co)
    assert s["ec2_count"] == 2
    assert s["ec2_savings"] == pytest.approx(15.5)
    assert s["ebs_count"] == 1
    assert s["ebs_savings"] == pytest.approx(2.0)
    assert s["lambda_count"] == 1
    assert s["lambda_savings"] == pytest.approx(0.5)
    assert s["asg_count"] == 3


def test_co_summary_handles_recommendation_without_options():
    co = {"instanceRecommendations": [{"recommendationOptions": []}]}
    s = analyze.co_savings_summary(co)
    assert s["ec2_count"] == 1
    assert s["ec2_savings"] == 0.0


def test_co_summary_handles_missing_savings_opportunity():
    co = {"instanceRecommendations": [{"recommendationOptions": [{}]}]}
    s = analyze.co_savings_summary(co)
    assert s["ec2_count"] == 1
    assert s["ec2_savings"] == 0.0
