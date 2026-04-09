---
name: dcd-run-server-pipe
description: Validate, upload, and optionally run a DCD pipe on a remote DCD server when the user wants server-side execution.
---
# DCD Run Server Pipe

## Purpose

Deploy a local pipe to a DCD server and optionally create a job run against a chosen dataset.

## Read First

Use these references in order:

1. `AGENTS.md`
2. `README.md`
3. `reference_repo/dcd-cli/docs/cli.md`
4. `reference_repo/dcd-cli/docs/pipe.md`

## Required Inputs

- target `pipe_dir`
- `input_dataset`
- optional `output_dataset`
- optional deployment mode: `auto`, `register`, or `update`

If the conversation does not identify a single pipe or dataset, ask the user before execution.

## Required Environment

Read `.server_info` when present and load:

- `DCD_HOST`
- `DCD_TOKEN`
- optional `DCD_AUTHOR`

If the active CLI flow expects `DCD_SECRET`, map it first:

```bash
export DCD_SECRET="$DCD_TOKEN"
```

The local environment also needs:

- `reference_repo/dcd`
- `reference_repo/dcd-cli`
- an active Python environment where `dcd` is available, or a fallback path for
  `python3 -m dcd_cli.cli`

## Workflow

1. Resolve the target pipe from conversation context or an explicit user path.
2. Confirm the pipe contains `manifest.yaml`.
3. Parse the pipe `name` from `manifest.yaml`.
4. Resolve `input_dataset`.
5. Derive a default `output_dataset` when none is provided, if the user wants a job run.
6. Validate the pipe with `dcd pipe validate` or `python3 -m dcd_cli.cli pipe validate`.
7. Probe the server for the pipe slug:
   - `200` -> update
   - `404` -> register
8. Upload the pipe using the selected mode.
9. If requested, create a job using the DCD jobs API.
10. Return pipe slug, pipe version, host, dataset names, job id, and initial status.

## Failure Handling

- Missing host or token: stop and ask for the missing values.
- Ambiguous pipe or dataset: ask for one explicit choice.
- Validation failure: return the first actionable error.
- Upload failure: return the HTTP status plus response body when available.
- Job creation failure: return the HTTP status plus response body.
- Sandbox or runtime failure: report the root cause and any concrete remediation hint.

## Expected Output

Return a compact report that includes:

- `DCD_HOST`
- resolved pipe path and pipe name
- register or update mode
- input and output datasets
- job id and status when a job is created
