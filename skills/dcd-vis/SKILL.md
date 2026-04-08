---
name: dcd-vis
description: Start or reuse a local DCD viewer session and verify that target datasets are visible in the UI.
---
# DCD Visualization

## Purpose

Launch the local DCD viewer, log in, and confirm that one or more datasets can be browsed successfully.

## Required Inputs

- one or more target dataset names

Infer datasets from the conversation when possible. If multiple plausible datasets exist and the intent is ambiguous, ask the user to choose.

## Required Environment

Read `.server_info` when present and load:

- `DCD_LOGIN_EMAIL`
- `DCD_LOGIN_PASSWORD`
- `DCD_APP_HOST`
- `DCD_APP_PORT`

Local runtime dependencies:

- `reference_repo/dcd`
- datasets available under the local DCD workspace

## Workflow

1. Resolve target datasets from the conversation.
2. Make sure each dataset exists in the local DCD dataset area.
3. Export `PYTHONPATH=reference_repo/dcd`.
4. Start the DCD viewer if it is not already running.
5. Open the login page at `http://<DCD_APP_HOST>:<DCD_APP_PORT>/login`.
6. Authenticate with the configured credentials.
7. Navigate to the datasets UI and verify the requested datasets are present.
8. Open at least one item from each resolved dataset when possible.

## Failure Handling

- Missing login config: stop and ask for the missing values.
- Missing dataset: report which datasets could not be resolved.
- Viewer startup failure: return the first failing command or traceback summary.
- Login/UI failure: report the exact failing step.

## Expected Output

Return:

- viewer URL
- login identity used
- per-dataset visibility result
- first blocking issue if verification fails
