---
name: dcd-server-operations
description: "Use when connecting to a DCD server for general server-side operations: checking access, validating/registering/updating pipes, creating and polling jobs, managing project resources, inspecting datasets, and recording dataset/job/pipe versions."
---
# DCD Server Operations

## Purpose

Use this skill for DCD server-side work from this repo:

- connect to a remote or local DCD server
- validate, register, update, or fetch pipes
- create and poll pipe jobs
- inspect datasets, jobs, pipes, and issues
- create/read/update project membership for datasets, pipes, jobs, skills, and issues
- record enough server metadata to make later debug iterations reproducible

For pipe authoring semantics, `reference_repo/dcd-cli` remains the source of truth. For
server API behavior, use `reference_repo/dcd-server`.

## Read First

Use these references when relevant:

1. `AGENTS.md`
2. `reference_repo/dcd-cli/docs/cli.md`
3. `reference_repo/dcd-cli/docs/pipe.md`
4. `reference_repo/dcd-server/dataclawdev/web/routes/`
5. `reference_repo/dcd-server/dataclawdev/web/db/`

Do not modify `reference_repo/*` unless the user explicitly asks for upstream source changes.

## Environment

Read `.server_info` when present. It usually defines:

- `DCD_HOST`
- `DCD_TOKEN`
- optional `DCD_AUTHOR`

Many DCD CLI docs call the token `DCD_SECRET`; map it before CLI calls:

```bash
set -a
source .server_info
export DCD_SECRET="$DCD_TOKEN"
set +a
```

Never print token values. When capturing command outputs, avoid echoing environment variables.

## Access Checks

Prefer `curl` or the DCD CLI for server probes. They set request headers that the server/gateway
accepts more reliably than bare Python `urllib`.

Good first checks:

```bash
curl -sS -H "Authorization: Bearer $DCD_TOKEN" \
  "${DCD_HOST%/}/api/pipes" >/tmp/dcd_pipes.json

curl -sS -H "Authorization: Bearer $DCD_TOKEN" \
  "${DCD_HOST%/}/api/projects" >/tmp/dcd_projects.json
```

If using Python HTTP clients, set a normal User-Agent:

```python
headers = {
    "Authorization": f"Bearer {token}",
    "User-Agent": "dcd-cli/codex",
    "Accept": "application/json",
}
```

Known trap: a Python `urllib` request without a suitable User-Agent may be rejected by the
gateway with a 403 body like `error code: 1010`. Recheck with `curl` before concluding that the
DCD token or API is broken.

## Project Slugs

Project API paths use the project `slug`, not the display `name`.

Example: a project displayed as `debug_wiki_to_md` may have slug `debug-wiki-to-md`.

Find the slug first:

```bash
curl -sS -H "Authorization: Bearer $DCD_TOKEN" \
  "${DCD_HOST%/}/api/projects" >/tmp/dcd_projects.json
```

Then use:

```text
/api/projects/<slug>
/api/projects/<slug>/resources
/api/datasets?project=<slug>
/api/pipes?project=<slug>
/api/jobs?project=<slug>
/api/issues?project=<slug>
```

## Pipe Upload Flow

1. Resolve `pipe_dir` and check it contains `manifest.yaml`.
2. Confirm the manifest `name` is stable and valid: lowercase letters, digits, underscores, and
   starts with a letter.
3. Validate locally and against the server:

```bash
PYTHONPATH=reference_repo/dcd-cli python -m dcd_cli.cli pipe validate \
  <pipe_dir> --host "${DCD_HOST%/}"
```

4. Probe whether the pipe exists:

```bash
curl -sS -o /tmp/pipe.json -w 'http_code=%{http_code}\n' \
  -H "Authorization: Bearer $DCD_TOKEN" \
  "${DCD_HOST%/}/api/pipes/<pipe_name>"
```

5. If 404, register:

```bash
PYTHONPATH=reference_repo/dcd-cli python -m dcd_cli.cli pipe register \
  <pipe_dir> --host "${DCD_HOST%/}" --changelog "<short change>"
```

6. If 200, update:

```bash
PYTHONPATH=reference_repo/dcd-cli python -m dcd_cli.cli pipe update \
  <pipe_dir> --host "${DCD_HOST%/}" --changelog "<short change>"
```

7. Record pipe name, server version, commit hash, changelog, and local git hash.

For debug iterations, prefer a stable debug pipe name and update the same server pipe across
rounds instead of creating many near-identical names.

## Run Pipe Job

Create jobs with `POST /api/jobs`. Use `steps` for the current multi-step shape, even for a
single pipe:

```json
{
  "input_dataset": "source_dataset_name",
  "output_dataset": "stable_output_dataset_name",
  "runner_type": "local",
  "runner_config": {},
  "steps": [
    {
      "pipe_slug": "pipe_name",
      "pipe_version": 1,
      "config": {}
    }
  ]
}
```

Submit with curl:

```bash
curl -sS -X POST "${DCD_HOST%/}/api/jobs" \
  -H "Authorization: Bearer $DCD_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @payload.json > job_initial.json
```

Poll:

```bash
curl -sS -H "Authorization: Bearer $DCD_TOKEN" \
  "${DCD_HOST%/}/api/jobs/runs/<job_id>" > job_final.json
```

Record:

- job id and status
- input dataset name/version
- output dataset name/version
- pipe slug/version/commit
- config
- items in/out
- error/log path when failed

If an output dataset name is reused, DCD creates/updates server-side dataset versions under that
stable name. Record the version number returned by the job.

## Project Resource Operations

Supported project resource types:

```text
dataset, pipe, skill, job, issue
```

Add resources:

```bash
cat > /tmp/add_resource.json <<'JSON'
{
  "resource_type": "dataset",
  "items": [
    {"id": "dataset_name", "name": "dataset_name"}
  ]
}
JSON

curl -sS -X POST "${DCD_HOST%/}/api/projects/<project_slug>/resources" \
  -H "Authorization: Bearer $DCD_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/add_resource.json
```

Use these resource ids:

- dataset: dataset name
- pipe: pipe slug/name
- job: job id as a string
- issue: issue id
- skill: skill slug/name

List resources:

```bash
curl -sS -H "Authorization: Bearer $DCD_TOKEN" \
  "${DCD_HOST%/}/api/projects/<project_slug>/resources"
```

Removing a project resource only removes project membership; it does not delete the underlying
dataset, pipe, job, skill, or issue.

## Dataset And Version Checks

List project datasets:

```bash
curl -sS -H "Authorization: Bearer $DCD_TOKEN" \
  "${DCD_HOST%/}/api/datasets?project=<project_slug>"
```

Dataset list responses may use `datasets` rather than `items`; inspect the response shape before
writing parsers.

For traceability, keep a task-local file that maps:

- stable dataset name
- dataset version number
- source dataset and version
- producing pipe and version
- job id
- config
- local artifact path, if any
- any local-vs-DCD modality differences

## Failure Handling

- `403` with `error code: 1010`: retry with `curl` or add a normal User-Agent before treating it
  as an auth failure.
- `404 Project not found`: check project slug; do not assume display name equals slug.
- `404 Pipe not found`: register if this is a new pipe; update only if it exists.
- validation failure: fix the first manifest/import/signature error before upload.
- job creation failure: save HTTP status and body; check `pipe_slug`, `pipe_version`,
  `input_dataset`, and config schema.
- job runtime failure: fetch job detail/logs and report the concrete exception, failed item
  count, and whether an output dataset/version was created.

## Expected Final Report

For server operations, return a compact summary with:

- host and project slug/name
- pipe name/version/commit for uploads
- input/output dataset names and versions for jobs
- job id/status/items in/out
- project resources added or updated
- local files where payloads/responses/version trace were saved
- any blockers or follow-up actions
