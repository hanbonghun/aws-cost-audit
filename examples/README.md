# Examples

## `sample-report/`

Output of one full audit run with account ID, IAM principal, resource IDs, and resource names replaced with placeholders. Use it to see what `aws-cost-audit` produces before running it against a real account.

- `01-cost-report.md` — full cost report with summary, idle resources, ALB / NAT / RDS / ElastiCache / EBS tables
- `02-problems.md` — findings grouped by severity (`[HIGH]` / `[MED]` / `[LOW]`)
- `03-improvements.md` — Phase 1 / 2 / 3 action plan with risk, validation, rollback
- `99-methodology.md` — data sources and limitations
- `data/` — per-category CSVs plus `master_summary.json`

Dollar amounts and dates are kept so the structure is realistic.

## `scrub.py`

CLI that takes a real `audit-output/<date>/` directory and produces a sanitized copy. Replacements are deterministic — the same input always produces the same output. Use it to share an audit result publicly (e.g. in an issue or a slide deck) without leaking customer-specific data.

```bash
python examples/scrub.py <input_dir> <output_dir>

# With extra terms (e.g. company-distinctive names not caught by the heuristics):
python examples/scrub.py <input_dir> <output_dir> --also-redact ./my-terms.txt
```

What gets replaced:

| Source pattern | Replacement |
|---|---|
| AWS account IDs (12-digit) | `123456789012` |
| IAM user / role ARN (`arn:aws:iam::…:user/…`) | `arn:aws:iam::123456789012:role/aws-cost-audit-reader` |
| Resource IDs (`i-`, `vol-`, `snap-`, `vpc-`, `nat-`, `sg-`, `subnet-`, `eni-`, `ami-`, `rtb-`, `tgw-`, `lt-`, `eipalloc-`, …) | counter-based fakes (`i-00000000000000001`, …; values are zero-padded hex up to 17 chars) |
| Resource names (EC2 `Name` tags and other non-`aws:*` tag values, ALB / RDS / cache identifiers, Lambda / log group / S3 bucket names, CloudFront origins, Route53 zones, ASG names, launch templates, target groups, Compute Optimizer recommendation tag values) | role-based fakes (`prod-app-3`, `dev-db-1`, …) |
| CloudFront distribution IDs (`E[A-Z0-9]{12,15}`) | counter-based (`E0000000000001`, …) |
| CloudFront distribution domains (`d…cloudfront.net`) | counter-based (`d0000000000001.cloudfront.net`, …) |
| Route 53 hosted-zone IDs (`Z[A-Z0-9]{13,20}`) | counter-based (`Z0000000000001`, …) |
| ELB / target-group ARN hex suffixes (the 16-hex trailing token in `loadbalancer/…/…/…`) | fixed `0123456789abcdef` |
| UUIDs (request-id format `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) | counter-based zero-UUID variants |
| Public IPv4 addresses | `192.0.2.1` (RFC 5737 TEST-NET-1). Private ranges kept. |
| ELB / NLB / ALB DNS names | `example-app-alb-12345.<region>.elb.amazonaws.com` |
| Terms from `--also-redact` | `REDACTED` (case-insensitive, word-boundary) |
| JSON `ResponseMetadata` blocks (raw boto3 response telemetry) | dropped entirely |

What is NOT scrubbed:

- Dollar amounts (kept so the sample shows realistic numbers)
- Dates and timestamps
- AWS service names, instance types, region codes

## Regenerating `sample-report/`

If `report.py` changes, the sample can be regenerated from the scrubbed `master_summary.json` without re-running `audit.py`:

```python
import json, sys
sys.path.insert(0, "scripts")
from lib import report

with open("examples/sample-report/data/master_summary.json", encoding="utf-8") as f:
    data = json.load(f)
report.render_all("examples/sample-report", data)
```
