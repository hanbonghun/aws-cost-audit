"""Replace account-, resource-, and name-level details in an audit-output
directory so the result can be shared publicly. Deterministic: the same input
always produces the same output.

Usage:
    python examples/scrub.py <input_dir> <output_dir>
    python examples/scrub.py audit-output/2026-05-28 examples/sample-report

Replacements:
- AWS account IDs (12-digit, the one found in master_summary.json) → 123456789012
- IAM user/role ARNs (arn:aws:iam::...:user/...) → arn:aws:iam::123456789012:role/aws-cost-audit-reader
- AWS resource IDs (i-, vol-, snap-, vpc-, nat-, sg-, subnet-, eni-, ami-, rtb-, acl-, eipalloc-, tgw-, pl-) → counter-based fakes
- ELB / NLB / ALB DNS names → "<env>-app-N-alb-XXXXX.region.elb.amazonaws.com"
- Public IPv4 addresses → 192.0.2.1 (RFC 5737 TEST-NET-1). Private ranges kept.
- Free-form resource names harvested from master_summary.json (EC2 Name tag, ALB Name, RDS Id, ElastiCache Id, NAT VpcId names if present) → "<env>-<role>-<n>" style fakes.

The script does NOT scrub:
- dollar amounts (kept so the sample shows realistic numbers)
- dates and timestamps
- AWS service names, instance types, region codes

Note: a one-line summary (counts only) is printed to stderr. The real → fake
mapping is kept in memory; it is intentionally not written to disk because the
mapping itself can be used to reverse the scrub.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FAKE_ACCOUNT = "123456789012"
FAKE_IAM_ARN = f"arn:aws:iam::{FAKE_ACCOUNT}:role/aws-cost-audit-reader"

ID_PREFIXES = (
    "i", "vol", "snap", "vpc", "nat", "sg", "subnet", "eni", "ami",
    "rtb", "acl", "tgw", "pl", "lt", "eipalloc", "igw",
)
ID_PATTERN = re.compile(rf"\b({'|'.join(ID_PREFIXES)})-[0-9a-f]{{8,17}}\b")
TWELVE_DIGITS = re.compile(r"\b\d{12}\b")
IAM_USER_ARN = re.compile(r"arn:aws:iam::\d{12}:user/[A-Za-z0-9.+\-_=,@]+")
ELB_DNS = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9-]*)-\d+\.([a-z0-9-]+)\.elb\.amazonaws\.com\b")
ELB_ARN_SUFFIX = re.compile(r"(loadbalancer/(?:app|net)/[^/]+/)[0-9a-f]{16}\b")
TG_ARN_SUFFIX = re.compile(r"(targetgroup/[^/]+/)[0-9a-f]{16}\b")
CLOUDFRONT_ID = re.compile(r"\bE[A-Z0-9]{12,15}\b")
CLOUDFRONT_DOMAIN = re.compile(r"\bd[a-z0-9]{12,15}\.cloudfront\.net\b")
R53_ZONE_ID = re.compile(r"\bZ[A-Z0-9]{13,20}\b")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
IPV4 = re.compile(r"\b(?:25[0-5]|2[0-4]\d|[01]?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d?\d)){3}\b")


def _is_private_ip(ip: str) -> bool:
    parts = [int(p) for p in ip.split(".")]
    if parts[0] == 10:
        return True
    if parts[0] == 172 and 16 <= parts[1] <= 31:
        return True
    if parts[0] == 192 and parts[1] == 168:
        return True
    if parts[0] == 127:
        return True
    return False


class Scrubber:
    def __init__(self, extra_redact: list[str] | None = None) -> None:
        self.real_account: str | None = None
        self.id_map: dict[str, str] = {}
        self.id_counter: dict[str, int] = {}
        self.name_map: dict[str, str] = {}
        self.name_counter: dict[tuple[str, str], int] = {}
        self.opaque_map: dict[str, str] = {}
        self.opaque_counter: dict[str, int] = {}
        self.extra_redact: list[str] = sorted(
            (extra_redact or []), key=len, reverse=True
        )

    def _fake_opaque(self, kind: str, real: str, template: str) -> str:
        """Counter-based opaque-token mapping (CloudFront ID, R53 zone, UUID, …).

        `template` is a format string with a single `{n}` placeholder.
        """
        if real in self.opaque_map:
            return self.opaque_map[real]
        n = self.opaque_counter.get(kind, 0) + 1
        self.opaque_counter[kind] = n
        fake = template.format(n=n)
        self.opaque_map[real] = fake
        return fake

    def _fake_id(self, match: re.Match[str]) -> str:
        real = match.group(0)
        if real in self.id_map:
            return self.id_map[real]
        prefix = match.group(1)
        n = self.id_counter.get(prefix, 0) + 1
        self.id_counter[prefix] = n
        fake = f"{prefix}-{n:017x}"
        self.id_map[real] = fake
        return fake

    def _fake_account(self, match: re.Match[str]) -> str:
        real = match.group(0)
        if real == FAKE_ACCOUNT:
            return real
        return FAKE_ACCOUNT

    def _fake_name(self, real: str) -> str:
        if real in self.name_map:
            return self.name_map[real]
        low = real.lower()

        if "bastion" in low:
            role = "bastion"
        elif "postgres" in low or "mysql" in low or "mariadb" in low or low.endswith("-db") or low == "db":
            role = "db"
        elif "cache" in low or "redis" in low or "memcached" in low:
            role = "cache"
        elif "-alb" in low or low.endswith("alb") or "-lb" in low:
            role = "lb"
        elif "-ci" in low or "cicd" in low or "build" in low:
            role = "ci"
        elif "apm" in low or "monitor" in low or "metric" in low:
            role = "obs"
        elif "ecs" in low or "service" in low or "app" in low or "server" in low:
            role = "app"
        elif "dashboard" in low or "redash" in low or "metabase" in low or "tableau" in low:
            role = "bi"
        else:
            role = "app"

        if "prod" in low:
            env = "prod"
        elif "stag" in low or "staging" in low:
            env = "stag"
        elif "dev" in low:
            env = "dev"
        else:
            env = "shared"

        key = (env, role)
        n = self.name_counter.get(key, 0) + 1
        self.name_counter[key] = n

        if role == "lb":
            fake = f"{env}-app-{n}-alb"
        elif role == "cache":
            fake = f"{env}-app-{n}-cache-001"
        elif role == "db":
            fake = f"{env}-app-{n}-postgres"
        else:
            fake = f"{env}-{role}-{n}"
        self.name_map[real] = fake
        return fake

    def _maybe_collect(self, value) -> None:
        """Register a name only if it looks like a custom resource name.

        Skip values that are short, all-numeric, contain whitespace, or look
        like common categorical tokens — to avoid replacing substrings inside
        AWS-managed strings (region codes, distribution IDs, ARNs, …).
        """
        if not isinstance(value, str):
            return
        v = value.strip()
        if len(v) < 5:
            return
        if v.isdigit():
            return
        if " " in v or "\t" in v:
            return
        if v.lower() in {"true", "false", "none", "null", "prod", "stag",
                         "staging", "production", "dev", "development",
                         "shared", "active", "inactive", "default"}:
            return
        self._fake_name(v)

    _AWS_TAG_WHITELIST = {
        "aws:autoscaling:groupName",
        "aws:cloudformation:stack-name",
    }

    def _collect_tags(self, item: dict) -> None:
        for k, v in (item.get("Tags") or {}).items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            if k.startswith("aws:") and k not in self._AWS_TAG_WHITELIST:
                continue
            self._maybe_collect(v)

    def _collect_raw_tags(self, obj) -> None:
        """Walk an object and collect values from `{key, value}` boto3-style tag dicts.

        This catches Compute Optimizer recommendation tags and any other raw
        AWS API response that hasn't been flattened to a plain dict.
        """
        if isinstance(obj, dict):
            keys = set(obj.keys())
            if keys == {"key", "value"} and isinstance(obj.get("value"), str):
                k = obj.get("key")
                if isinstance(k, str) and not k.startswith("aws:"):
                    self._maybe_collect(obj["value"])
            else:
                for v in obj.values():
                    self._collect_raw_tags(v)
        elif isinstance(obj, list):
            for item in obj:
                self._collect_raw_tags(item)

    def collect_names(self, summary: dict) -> None:
        for e in summary.get("ec2", []) or []:
            self._maybe_collect(e.get("Name"))
            self._collect_tags(e)
        for a in summary.get("albs", []) or []:
            self._maybe_collect(a.get("Name"))
            self._collect_tags(a)
        for r in summary.get("rds", []) or []:
            self._maybe_collect(r.get("Id"))
        for c in summary.get("ec", []) or []:
            self._maybe_collect(c.get("Id"))
        orphans = summary.get("orphans") or {}
        for s_ in orphans.get("stopped_ec2", []) or []:
            self._maybe_collect(s_.get("Name"))
            self._collect_tags(s_)
        for asg in orphans.get("auto_scaling_groups", []) or []:
            if isinstance(asg, dict):
                self._maybe_collect(asg.get("Name"))
        for lt in orphans.get("launch_templates", []) or []:
            if isinstance(lt, dict):
                self._maybe_collect(lt.get("Name"))
        for tg in orphans.get("target_groups", []) or []:
            if isinstance(tg, dict):
                self._maybe_collect(tg.get("Name"))
        self._collect_raw_tags(summary.get("co"))
        for lf in summary.get("lambdas", []) or []:
            self._maybe_collect(lf.get("Name"))
        for lg in summary.get("logs", []) or []:
            self._maybe_collect(lg.get("Name"))
        for b in summary.get("buckets", []) or []:
            if isinstance(b, dict):
                self._maybe_collect(b.get("Name"))
            else:
                self._maybe_collect(b)
        for cf in summary.get("cloudfront", []) or []:
            if not isinstance(cf, dict):
                continue
            self._maybe_collect(cf.get("Comment"))
            origin = cf.get("Origin")
            if isinstance(origin, str):
                self._maybe_collect(origin.split(".")[0])
        for z in summary.get("zones", []) or []:
            if isinstance(z, dict):
                name = z.get("Name")
                if isinstance(name, str):
                    self._maybe_collect(name.rstrip("."))

    def scrub_text(self, text: str) -> str:
        for real, fake in sorted(self.name_map.items(), key=lambda kv: -len(kv[0])):
            text = re.sub(rf"(?<![A-Za-z0-9_-]){re.escape(real)}(?![A-Za-z0-9_])", fake, text)
        for term in self.extra_redact:
            text = re.sub(rf"(?<![A-Za-z0-9_-]){re.escape(term)}(?![A-Za-z0-9_])", "REDACTED", text, flags=re.IGNORECASE)
        text = IAM_USER_ARN.sub(FAKE_IAM_ARN, text)
        text = ID_PATTERN.sub(self._fake_id, text)

        text = CLOUDFRONT_ID.sub(
            lambda m: self._fake_opaque("cf", m.group(0), "E{n:013d}"), text
        )
        text = CLOUDFRONT_DOMAIN.sub(
            lambda m: self._fake_opaque("cfd", m.group(0), "d{n:013d}.cloudfront.net"),
            text,
        )
        text = R53_ZONE_ID.sub(
            lambda m: self._fake_opaque("z", m.group(0), "Z{n:013d}"), text
        )
        text = UUID_RE.sub(
            lambda m: self._fake_opaque(
                "uuid", m.group(0).lower(),
                "00000000-0000-0000-0000-{n:012d}",
            ),
            text,
        )
        text = ELB_ARN_SUFFIX.sub(r"\g<1>0123456789abcdef", text)
        text = TG_ARN_SUFFIX.sub(r"\g<1>0123456789abcdef", text)

        text = TWELVE_DIGITS.sub(self._fake_account, text)

        def _elb(m: re.Match[str]) -> str:
            region = m.group(2)
            return f"example-app-alb-12345.{region}.elb.amazonaws.com"
        text = ELB_DNS.sub(_elb, text)

        def _ip(m: re.Match[str]) -> str:
            ip = m.group(0)
            return ip if _is_private_ip(ip) else "192.0.2.1"
        text = IPV4.sub(_ip, text)
        return text

    def scrub_json(self, obj):
        if isinstance(obj, dict):
            return {
                k: self.scrub_json(v)
                for k, v in obj.items()
                if k != "ResponseMetadata"
            }
        if isinstance(obj, list):
            return [self.scrub_json(v) for v in obj]
        if isinstance(obj, str):
            return self.scrub_text(obj)
        return obj


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrub identifying details from an audit-output directory."
    )
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--also-redact",
        type=Path,
        default=None,
        help="path to a text file with one extra term per line; each match is replaced with REDACTED.",
    )
    args = parser.parse_args()

    in_dir = args.input_dir
    out_dir = args.output_dir
    if not in_dir.is_dir():
        print(f"input dir not found: {in_dir}", file=sys.stderr)
        return 2

    extra_terms: list[str] = []
    if args.also_redact:
        for line in args.also_redact.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                extra_terms.append(line)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(exist_ok=True)

    s = Scrubber(extra_redact=extra_terms)

    master_path = in_dir / "data" / "master_summary.json"
    if master_path.exists():
        with master_path.open(encoding="utf-8") as f:
            summary = json.load(f)
        if summary.get("account"):
            s.real_account = str(summary["account"])
        s.collect_names(summary)

    for md in sorted(in_dir.glob("*.md")):
        out = out_dir / md.name
        out.write_text(s.scrub_text(md.read_text(encoding="utf-8")), encoding="utf-8")

    csv_dir = in_dir / "data"
    if csv_dir.is_dir():
        for csv_path in sorted(csv_dir.glob("*.csv")):
            text = csv_path.read_text(encoding="utf-8")
            (out_dir / "data" / csv_path.name).write_text(
                s.scrub_text(text), encoding="utf-8"
            )

    if master_path.exists():
        with master_path.open(encoding="utf-8") as f:
            data = json.load(f)
        scrubbed = s.scrub_json(data)
        (out_dir / "data" / "master_summary.json").write_text(
            json.dumps(scrubbed, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "account_id_replaced": bool(s.real_account),
                "ids_count": sum(s.id_counter.values()),
                "names_count": len(s.name_map),
                "extra_redact_count": len(s.extra_redact),
            },
            indent=2,
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
