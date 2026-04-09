---
name: dcd-local-server
description: Start, verify, and troubleshoot the local DCD server and viewer for this repo, including dataset visibility and local account setup.
---
# DCD Local Server

## Purpose

Use this skill when a user wants to:

- start or restart the local DCD server
- open the local viewer in a browser
- verify that local datasets appear in the UI
- create or validate a local viewer account
- debug local problems such as login failure, missing datasets, or frontend 404s

This skill covers the full local server workflow. Dataset visibility in the UI is one part of
that workflow, not a separate skill.

## Read First

Use these references in order:

1. `AGENTS.md`
2. `README.md`
3. `reference_repo/dcd/README.md`
4. `reference_repo/dcd/docs/webapp.md`

Use `reference_repo/dcd` as the source of truth for local web UI behavior.

## Scope Rules

- Do not modify `reference_repo/dcd` just to make local startup easier unless the user explicitly
  asks for upstream source changes.
- Prefer runtime fixes: environment variables, start commands, local work dirs, dataset
  placement, account creation, and browser-state cleanup.
- Treat `workspace/` as repo-local runtime state. It may not exist in a fresh clone; create it
  when needed.
- Prefer a repo-local server work dir under `workspace/` for new local runs unless the user asks
  for another location.
- In this repo, treat `workspace/dataclawdev-server-data/` as the default local server work dir
  by convention.
- Treat `workspace/viewer_datasets/` as the conventional repo-local dataset link location for
  local viewer work when such a link-based setup is useful.

## Required Inputs

Infer from the conversation when possible:

- target host and port
- optional dataset names to verify
- whether a local account should be created or checked

Read `.server_info` when present and use:

- `DCD_LOGIN_EMAIL`
- `DCD_LOGIN_PASSWORD`
- `DCD_APP_HOST`
- `DCD_APP_PORT`

If local viewer work is requested and `workspace/` does not exist, create it.

## Key Runtime Facts

- The local web UI lives in `reference_repo/dcd`.
- The built frontend must exist under `reference_repo/dcd/dataclawdev/server/static/`.
- The active server decides which dataset directory is visible in the UI.
- The local server work dir should stay repo-local when possible, typically somewhere under
  `workspace/`.
- By repo convention, the preferred local server work dir is
  `workspace/dataclawdev-server-data/`.
- By repo convention, `workspace/viewer_datasets/` can be used as a convenient repo-local place
  to prepare dataset links for the viewer workflow.

## Standard Workflow

### 1. Confirm the active server

1. Check whether a DCD server is already listening on the target port.
2. Inspect the running process command and working directory.
3. Confirm whether it is serving this repo's `reference_repo/dcd` or some other checkout.
4. Identify which work dir and dataset directory that active server is actually using.

If a different checkout is serving the port, say that explicitly before doing anything else.

### 2. Validate prerequisites

Check:

- `reference_repo/dcd/frontend/package.json`
- `reference_repo/dcd/dataclawdev/server/static/index.html`
- `reference_repo/dcd/datasets/`
- the chosen local work dir if one is already known, usually
  `workspace/dataclawdev-server-data/`

If `static/index.html` is missing, build the frontend first:

```bash
cd reference_repo/dcd/frontend
npm ci
npm run build
```

### 3. Prepare local runtime directories

For a fresh clone, create `workspace/` if needed.

Put local-only artifacts under `workspace/`, for example:

- viewer work dir
- dataset links
- logs
- screenshots
- temporary dataset links

Do not rely on machine-specific absolute host paths outside the repo unless the user explicitly
asks for that setup.

### 4. Make datasets visible to the active server

If a target dataset exists only under `workspace/` or another repo-local location, make it
visible from the dataset directory used by the active local server.

Always verify visibility from the server's actual dataset root, not from convenience links or
assumptions.

If a repo-local dataset-link layout is useful, prefer `workspace/viewer_datasets/` as the
conventional staging location.

### 5. Start the local server

Preferred goal:

- serve `reference_repo/dcd`
- on the configured host and port
- with a repo-local work dir, usually `workspace/dataclawdev-server-data/`

After startup, verify:

- process exists
- port is listening
- `GET /api/auth/config` returns `200`
- `GET /login` returns the SPA HTML instead of a JSON 404

### 6. Create or verify the local account

If `.server_info` provides local credentials, check whether that user exists in the auth DB
associated with the active server work dir.

Use the DCD server tooling to create the account when needed. Then verify through the live HTTP
login endpoint.

Do not stop after checking SQLite directly. The real source of truth is whether:

```bash
POST /api/auth/login
```

accepts the credentials on the running server.

### 7. Verify datasets in the UI

For each requested dataset:

1. confirm it exists in the active server's dataset directory
2. confirm the server-side dataset scan sees it
3. confirm the UI can list it

If useful, open one representative item. If the UI cannot render a detail page for that dataset
type, report that plainly instead of assuming the dataset is broken.

## Common Problems

### Login says the account is not registered

Typical causes:

- the user was created in the wrong work dir
- the server on the port is a different DCD checkout
- the browser is talking to a different host or port than the one you verified

### `/login` or `/datasets` returns JSON 404

Typical causes:

- frontend assets were not built
- the wrong server instance is running
- the request is not reaching the expected SPA-serving app

### A dataset exists on disk but not in the UI

Typical causes:

- it was added to the wrong dataset directory
- the active server is reading a different checkout or work dir
- the dataset was added after startup and you only checked the filesystem

## Recommended Checks

Use checks like these, adapted to the chosen host and port:

```bash
curl -s http://127.0.0.1:8000/api/auth/config
curl -i -s http://127.0.0.1:8000/login | head
curl -i -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"guest@dcd.com","password":"123456"}'
ps -ef | rg 'python3 -m dataclawdev.server|uvicorn'
```

When multiple DCD checkouts may exist on one machine, also inspect:

- process cwd
- active work dir
- open `auth.db`
- active dataset directory

## Expected Output

Return a compact report with:

- viewer URL
- which `reference_repo/dcd` instance is serving it
- active work dir
- login identity used or created
- dataset visibility result
- first blocking issue if verification still fails
