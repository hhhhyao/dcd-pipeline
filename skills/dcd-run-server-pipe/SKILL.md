---
name: dcd-run-server-pipe
description: Validate, upload, and optionally run a DCD pipe on a remote DCD server when the user wants server-side execution.
---
# DCD Run Server Pipe

## Purpose

Deploy a local pipe to a DCD server and create a job run against a chosen dataset.

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

The local environment also needs:

- `reference_repo/dcd`
- `reference_repo/dcd-cli`

## Workflow

1. Resolve the target pipe from conversation context or an explicit user path.
2. Confirm the pipe contains `manifest.yaml` and `requirements.txt`.
3. Parse the pipe `name` from `manifest.yaml`.
4. Resolve `input_dataset`.
5. Derive a default `output_dataset` when none is provided.
6. Export `PYTHONPATH=reference_repo/dcd:reference_repo/dcd-cli`.
7. Validate the pipe with `dcd pipe validate` or `python3 -m dcd_cli.cli pipe validate`.
8. Probe the server for the pipe slug:
   - `200` -> update
   - `404` -> register
9. Upload the pipe using the selected mode.
10. If requested, create a job using the DCD jobs API.
11. Return pipe slug, pipe version, host, dataset names, job id, and initial status.

## Failure Handling

- Missing host/token: stop and ask for the missing values.
- Ambiguous pipe or dataset: ask for one explicit choice.
- Validation failure: return the first actionable error.
- Job creation failure: return HTTP status plus response body.
- Sandbox/runtime failure: report the root cause and any concrete remediation hint.

## Expected Output

Return a compact report that includes:

- `DCD_HOST`
- resolved pipe path and pipe name
- register/update mode
- input and output datasets
- job id and status when a job is created
