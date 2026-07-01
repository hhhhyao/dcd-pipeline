# AGENTS.md

## Purpose

This file is for agents working in `dcd_pipeline`.

Use it for repository-specific rules, source-of-truth priorities, and execution constraints.
For developer onboarding and quickstart steps, see `README.md`.

## Startup Checklist

Before doing implementation, validation, or local server work:

1. Initialize the required reference submodule:

```bash
git submodule update --init --recursive reference_repo/dcd-cli
```

   Optional: sync `dcd-cli` to the latest upstream `main` (see `branch` in `.gitmodules`):

```bash
git submodule update --remote --merge reference_repo/dcd-cli
```

   Commit the updated `dcd-cli` submodule pointer in the parent repo when you intend to pin a new
   upstream revision for collaborators. Do not initialize, sync, or pin `reference_repo/dcd` or
   `reference_repo/dcd-server` unless the user explicitly asks and the private checkouts are
   accessible.

2. Confirm the required upstream reference repo exists:

- `reference_repo/dcd-cli`

   `reference_repo/dcd` and `reference_repo/dcd-server` are optional private references. It is
   acceptable for them to be absent or uninitialized.

3. If a command depends on local host or credentials, read `.server_info` when present.

4. This repo's local template uses `DCD_TOKEN`. If a CLI command or doc expects
   `DCD_SECRET`, map it first:

```bash
export DCD_SECRET="$DCD_TOKEN"
```

5. For DCD server API probes, prefer `dcd-cli` or `curl`. If using a Python HTTP
   client, set a normal `User-Agent`; bare `urllib` requests may be blocked by
   the gateway with HTTP 403 / `error code: 1010`.

6. Do not assume `workspace/` already exists. Create it only when needed.

## Normative References

When working on pipes, treat `reference_repo/dcd-cli` as the primary source of truth for:

- package structure
- manifest semantics
- runtime expectations
- validation behavior

Read in this order when relevant:

1. `reference_repo/dcd-cli/docs/pipe.md`
2. `reference_repo/dcd-cli/docs/cli.md`
3. `reference_repo/dcd-cli/docs/text-formats.md`
4. `reference_repo/dcd-cli/README.md`
5. `reference_repo/dcd-cli/pipe-demos/*/README.md`
6. `reference_repo/dcd-cli/skills/user/update-pipe/SKILL.md`

If repo-local habits conflict with those docs, follow the upstream docs.

## Repo Rules

### Structure

- `pipelines/`
  Deployable pipeline packages. Preferred layout:
  `pipelines/<family>/<pipe_name>/`
- `skills/`
  Repo-local agent workflow docs
- `reference_repo/`
  Reference repos managed as submodules. `dcd-cli` is required; `dcd` and `dcd-server` are optional
  private references.
- `workspace/`
  Repo-local runtime area for temporary or machine-specific artifacts

### Upstream Repos

Source-of-truth split:

- **Pipes** — `reference_repo/dcd-cli` (manifests, runtime semantics, `dcd` CLI, validation). This stays the normative reference for pipe work.
- **Server/runtime implementation** — `reference_repo/dcd-server` is an optional private
  reference. Use it only when the user explicitly needs server-side code details and the checkout is
  available.
- **Full-stack local viewer / frontend** — `reference_repo/dcd` is an optional private reference.
  Use it only when the user explicitly needs full-stack or UI implementation details and the
  checkout is available.

- Treat `reference_repo/dcd-cli` as the required upstream reference.
- Treat `reference_repo/dcd` and `reference_repo/dcd-server` as optional private references; do not
  assume they exist, track upstream, or should be updated.
- Prefer wrapper scripts, environment variables, local work dirs, symlinks, and repo-local
  helper docs over editing upstream code.
- Do not modify code under `reference_repo/dcd-cli`, `reference_repo/dcd`, or
  `reference_repo/dcd-server` unless the user explicitly asks for upstream source changes.
- If a local setup problem can be solved without upstream edits, solve it at the runtime or
  configuration layer instead.

## Pipe Rules

Each deployable pipe should usually stay self-contained and include:

- `manifest.yaml`
- `__init__.py` or `main.py`
- `requirements.txt`
- `README.md`
- `tests/`

When editing or creating a pipe:

- Keep pipe names valid Python package names: lowercase letters, digits, and underscores,
  starting with a letter.
- Keep runtime logic inside the pipe package, not in repo-root helper glue.
- Update `manifest.yaml`, implementation, tests, and pipe-local docs together when behavior
  changes.
- Make the pipe-local `README.md` describe the real input, output, config, and behavior.

## Runtime Rules

Normative detail lives in `reference_repo/dcd-cli/docs/pipe.md` under the runtime,
sandbox, volume, and network sections. For server-side execution detail, prefer remote API probes
and repo-local skills. If the optional private `reference_repo/dcd` checkout is available, these
docs can be used as background:

- `reference_repo/dcd/docs/manual/pipe.md`
- `reference_repo/dcd/docs/design/job-lifecycle.md`

Write pipe code with these assumptions:

- Treat the filesystem as allow-listed. Rely on pipe code, the venv, input datasets,
  `ctx.output_dir` for ingest, `$HOME` (`/home/pipe`), `/tmp`, and paths from `ctx.volumes`.
- Do not hard-code arbitrary host paths.
- Network is off unless the manifest sets `network: true`.
- Transform pipes should return data from the entry function instead of depending on writes to
  undocumented locations.
- Some local development setups may not enforce strict isolation, but pipe code should still be
  written as if only the allow-listed mounts exist.

## Testing and Validation

Tests for an active pipe should run in isolation.

Prefer:

- package-local imports
- fixture files under the pipe's own `tests/fixtures/`
- commands scoped to the specific pipe under test

Avoid:

- repo-root absolute paths
- test setup that depends on one developer machine layout
- hidden coupling to unrelated pipeline families

Typical test command:

```bash
pytest -q pipelines/<family>/<pipe_name>/tests
```

Example:

```bash
pytest -q pipelines/wiki/stage2_parse_html/tests
```

For pipe-level validation, use `dcd-cli` against the specific directory you changed:

```bash
dcd pipe validate pipelines/<family>/<pipe_name> --host "$DCD_HOST"
```

If a suitable `dcd` command is not available in the active environment, falling back to
`python3 -m dcd_cli.cli ...` is acceptable.

If you are preparing a new version, review the upload and update flow in
`reference_repo/dcd-cli/docs/cli.md` before changing manifests or release notes.

## Remote Server References

Use these docs when deploying pipes to a host or reasoning about server-side execution.

For repeatable DCD server operations, use the repo skill:

- `skills/dcd-server-operations/SKILL.md` — general DCD server connection and API
  workflow for access checks, pipe upload/update, job creation/polling, project
  resources, and dataset/job/pipe version tracing.

`dcd-cli`

- `reference_repo/dcd-cli/docs/cli.md`
- `reference_repo/dcd-cli/docs/pipe.md`

Optional private `dcd`

- `reference_repo/dcd/docs/api.md`
- `reference_repo/dcd/docs/design/job-lifecycle.md`
- `reference_repo/dcd/docs/design/remote-runner.md`
- `reference_repo/dcd/docs/design/runner.md`

Important server API notes:

- Project API paths use the project `slug`, not the display `name`.
- DCD resource ids are usually names/slugs: dataset name, pipe name, job id string,
  issue id, or skill name.
- For project-scoped lists, use query params such as
  `/api/datasets?project=<project_slug>` and `/api/pipes?project=<project_slug>`.
- Prefer stable output dataset names for repeated debug runs; record the resulting
  dataset version and producing job id in task-local docs.

## Local Web UI

The browser UI does not ship with `dcd-cli`. Older setups used `reference_repo/dcd`, but that
checkout is now an optional private reference.

Use these references:

- `skills/dcd-local-server/SKILL.md` when the task is about starting, verifying, or
  troubleshooting the local viewer
- `reference_repo/dcd/README.md` and `reference_repo/dcd/docs/webapp.md` only when the optional
  private checkout is available

For local viewer work in this repo:

- keep local runtime state under `workspace/`
- ensure requested datasets are visible from the dataset directory used by the active local DCD
  server
- do not assume auxiliary files under `workspace/` control the live UI

## Safety and Style

- Avoid printing secrets in commands, logs, tests, fixtures, or docs.
- Prefer small, composable Python helpers and explicit names.
- Preserve ASCII unless a file already requires non-ASCII.
- If local config keys need to change, preserve user values when possible.
- When a requirement is ambiguous, prefer the `dcd-cli` docs over project-specific habit.
