# Agent Guide

이 파일은 Codex, Claude Code 등 코드 에이전트가 이 저장소에서 작업할 때 따르는 공통 지침입니다. `CLAUDE.md`는 가능하면 이 파일과 같은 내용을 공유하는 링크(심볼릭 링크 또는 하드 링크)로 유지합니다. 내용을 바꿀 때는 `AGENTS.md`만 수정하세요.

## Project Summary

`aws-cost-audit`는 매월 1일 GitHub Actions에서 AWS 비용 감사를 실행하는 GitOps 기반 FinOps 도구입니다. Python 스크립트가 AWS 리소스와 비용 데이터를 읽고 Markdown/CSV/JSON 리포트를 만들며, Terraform은 GitHub OIDC, read-only 감사 역할, S3 리포트 버킷, SNS, Budgets, Cost Anomaly Detection을 구성합니다.

핵심 원칙은 **감사 대상 AWS 리소스에는 read-only** 입니다. 리포트 업로드용 S3 write와 알림용 SNS publish는 예외이며, Terraform은 이 도구 자체의 인프라를 생성/관리합니다.

## Repository Map

- `scripts/audit.py`: 감사 실행 진입점. 수집, 분석, 리포트 생성, 업로드/알림을 순서대로 조립합니다.
- `scripts/lib/collect.py`: boto3 기반 데이터 수집. 리전 병렬 실행, pagination, CloudWatch/Cost Explorer/Compute Optimizer 호출을 담당합니다.
- `scripts/lib/analyze.py`: idle, rightsizing, snapshot dependency, ALB/NAT/RDS/ElastiCache 판정 로직과 비용 추정 상수.
- `scripts/lib/report.py`: Markdown 리포트 4종, CSV, `master_summary.json` 생성.
- `scripts/lib/notify.py`: S3 업로드, SNS publish, Slack webhook 전송.
- `terraform/`: AWS 인프라. OIDC role, IAM policy, S3, SNS, Budgets, Anomaly Detection.
- `.github/workflows/`: 월간 감사, 수동 감사, Terraform validation workflow.
- `docs/`: 아키텍처, 셋업, 로드맵 문서.

## Non-Negotiable Safety Rules

- 감사 대상 리소스에는 `create`, `delete`, `modify`, `update`, `put` 계열 AWS API를 추가하지 마세요.
- 예외는 `scripts/lib/notify.py`의 리포트 업로드(`s3.upload_file`)와 알림(`sns.publish`, Slack webhook)입니다.
- 비용 정리 자동화처럼 실제 AWS 리소스를 바꾸는 기능은 이 저장소의 현재 범위를 벗어납니다. 그런 변경 요청이 오면 별도 설계, 명시적 승인, IAM 정책 리뷰가 먼저 필요합니다.
- 장기 AWS access key를 workflow, 코드, 문서 예시에 추가하지 마세요. GitHub Actions는 OIDC AssumeRole만 사용합니다.
- `terraform.tfvars`, `.env`, Slack webhook URL, AWS credentials, 실제 계정별 민감값은 커밋하지 마세요.
- `terraform plan/apply`나 `python scripts/audit.py`는 실제 AWS API를 호출합니다. 사용자가 요청했거나 안전한 자격증명/프로파일이 명확할 때만 실행하세요.

## Development Commands

Python dependencies:

```bash
python -m pip install -r scripts/requirements.txt
```

Python syntax check:

```bash
python -m compileall scripts
```

Local audit run, upload/notifications disabled:

```bash
cd scripts
unset S3_REPORT_BUCKET SNS_TOPIC_ARN SLACK_WEBHOOK_URL
export AWS_PROFILE=analysis-readonly
export AWS_REGION=ap-northeast-2
python audit.py
```

Terraform formatting and validation:

```bash
cd terraform
terraform fmt -recursive
terraform init -backend=false
terraform validate
```

Terraform plan usually needs repo variables:

```bash
TF_VAR_github_org=your-org TF_VAR_github_repo=aws-cost-audit terraform plan -no-color
```

On PowerShell, use `$env:TF_VAR_github_org="your-org"` style environment variables.

## Python Guidelines

- Target Python 3.11, matching GitHub Actions.
- Keep dependencies minimal. Current runtime dependencies are `boto3` and `botocore`.
- Use boto3 paginators through `_paginate()` where available.
- Use `_parallel_regions()` or bounded `ThreadPoolExecutor` for multi-region work; keep `BOTO_CFG` adaptive retries and connection pooling.
- Per-region unsupported services and `ClientError`s should log warnings and continue unless the whole audit cannot proceed.
- Keep collection, classification, reporting, and notification boundaries separate:
  - raw AWS reads in `collect.py`
  - business judgement in `analyze.py`
  - file rendering in `report.py`
  - external delivery in `notify.py`
- When adding an investigation:
  1. add a collector in `scripts/lib/collect.py`
  2. add classification or cost logic in `scripts/lib/analyze.py` if needed
  3. wire it in `scripts/audit.py`
  4. add Markdown/CSV output in `scripts/lib/report.py`
  5. update `README.md`, `docs/ARCHITECTURE.md`, and this guide if behavior or scope changes
- Price constants in `analyze.py` are approximate. Prefer Cost Explorer measured costs where possible, and label estimates clearly.
- Keep generated output under `audit-output/YYYY-MM-DD/`; do not commit generated audit results.

## Terraform Guidelines

- Run `terraform fmt -recursive` before finishing Terraform changes.
- Keep provider versions and Terraform minimum version in `terraform/versions.tf`.
- Keep variables typed and documented in `terraform/variables.tf`.
- Keep outputs focused on values needed by GitHub Secrets or operators.
- Preserve the local backend default. Add remote state only if the user explicitly asks for team/shared state.
- OIDC trust policy must stay scoped to the configured GitHub org/repo/branch.
- Use `count` or equivalent guard variables for optional resources.
- IAM policy changes require extra scrutiny. Avoid broad write permissions; S3/SNS exceptions must stay resource-scoped.

## GitHub Actions Guidelines

- Keep monthly and on-demand audit workflows behaviorally aligned unless the difference is intentional.
- Use `aws-actions/configure-aws-credentials` with OIDC. Do not add stored AWS keys.
- Keep Python version and dependency cache settings consistent across audit workflows.
- Terraform workflow should validate PR changes but should not apply infrastructure automatically unless explicitly requested.

## Documentation Guidelines

- Docs are primarily Korean; keep that style unless the user asks otherwise.
- Use concrete command blocks that work from the repository root or state the working directory.
- If code behavior and docs disagree, trust the code first, then update docs to match.
- For safety-sensitive wording, be precise about the difference between read-only AWS resource inspection and report delivery writes.

## Completion Checklist

Before saying work is complete:

- For Python changes, run `python -m compileall scripts`.
- For Terraform changes, run `terraform fmt -recursive` and `terraform validate` when Terraform is available.
- For GitHub Actions changes, inspect YAML syntax and confirm required secrets/env vars still line up with Terraform outputs.
- For docs-only changes, at least verify links/filenames and check `git diff`.
- Mention any verification that was skipped and why, especially if it would call live AWS APIs.
