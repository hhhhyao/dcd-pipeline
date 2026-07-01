---
name: dcd-fetch-review-issues
description: Use when pulling human review issues or annotations from a DCD server such as bluezone into a local, traceable debug cache for pipe debugging, bad-case triage, or follow-up implementation work.
---
# DCD Fetch Review Issues

## Purpose

Use this skill when human review results live in DCD issues and need to be pulled into the
local repo before debugging or implementing fixes.

The output should be a local cache with:

- an issue list snapshot
- one detail JSON per issue when the server exposes detail endpoints
- a short summary that records host, fetch time, filters, and issue count
- paths that can be referenced from round docs

## Inputs

Resolve these before fetching:

- DCD host, from `DCD_HOST` or `.server_info`
- DCD token, from `DCD_TOKEN`, `DCD_SECRET`, or `.server_info`
- output directory under `workspace/` or `debug/<project>/`
- optional filters: dataset, issue type, assignee, created time, status, or limit

Do not print tokens.

## Workflow

1. Read `.server_info` if present, then environment variables.
2. Normalize the host by removing a trailing slash.
3. Fetch the issue list from the server issue API.
4. Save the raw list response as `issues.json`.
5. For each issue with an ID, fetch and save detail JSON as `<issue_id>.json`.
6. If the API supports filters, prefer server-side filters; otherwise fetch then filter locally.
7. Write a compact fetch summary with host, output path, issue count, filters, and errors.
8. Use the local JSON cache for implementation and docs instead of repeatedly hitting the server.

The known bluezone path used successfully in this repo was:

```text
GET /api/issues
GET /api/issues/<issue_id>
```

Use the repo-level tool script:

```bash
python3 tools/dcd_debug/fetch_dcd_issues.py \
  --output-dir workspace/<project>/issues_latest
```

Useful options:

```bash
python3 tools/dcd_debug/fetch_dcd_issues.py \
  --issues-endpoint /api/issues \
  --detail-template '/api/issues/{id}' \
  --query-param dataset=<dataset_name> \
  --limit 50 \
  --output-dir workspace/<project>/issues_latest
```

The project-specific script that previously worked was:

```bash
python3 debug/stage2_bad_case_dataset/fetch_bluezone_issues.py \
  --output-dir workspace/md_lance/bluezone_issues_latest
```

Treat it as a historical example. Prefer the `tools/dcd_debug/` script for new projects.

## Output Layout

Recommended layout:

```text
workspace/<project>/issues_<date>/
  issues.json
  <issue_id>.json
  fetch_summary.json
```

For long-running projects, also maintain a stable `issues_latest` directory or symlink if that
matches repo habits.

## Troubleshooting

- **Missing host or token**: read `.server_info`; map `DCD_SECRET="$DCD_TOKEN"` if the local
  command expects `DCD_SECRET`.
- **HTTP 401 or 403**: token is missing, expired, for the wrong host, or lacks issue access.
- **HTTP 404 on `/api/issues`**: confirm the active server is a DCD server with issue support;
  check server docs or frontend network calls for the current endpoint.
- **Detail endpoint fails for some IDs**: keep the list snapshot, record failed IDs, and proceed
  with available details.
- **Large issue list**: use `--limit` for exploration, then rerun without a limit for the final
  traceable cache.
- **Ambiguous sample IDs**: preserve the raw issue body and attachments; do not rewrite IDs
  until they are matched against the dataset.
- **Secrets in logs**: redact authorization headers and any copied `.server_info` content.

## Expected Report

When finished, report:

- host name, without token
- output directory
- issue count and detail count
- filters used
- any failed issue IDs or endpoint problems
- how the cache should be referenced in the current debug round
