# dcd_pipeline

`dcd_pipeline` is a workspace for developing, testing, and maintaining DCD pipelines.

The repo is not tied to a single business domain. The checked-in `pipelines/wiki/` tree is a
working example of how a pipeline family can be organized, tested, and run locally.

## Quick Start

Use this path if you just cloned the repo and want to get to a runnable setup quickly.

### 1. Initialize the required reference submodule

```bash
git submodule update --init --recursive reference_repo/dcd-cli
```

This repo depends on `reference_repo/dcd-cli` for pipe authoring, CLI behavior, and
validation docs.

`reference_repo/dcd` and `reference_repo/dcd-server` may appear in older checkouts, but those
upstream repositories can be private and are no longer required references for this workspace.
Leave them uninitialized unless you explicitly need them and have access.

### Optional: Sync `dcd-cli` to upstream `main`

After init, or when you want the latest `dcd-cli` upstream:

```bash
git submodule update --remote --merge reference_repo/dcd-cli
```

Commit the updated `dcd-cli` submodule pointer in this repo if you want that revision recorded
for others. Do not update or pin `reference_repo/dcd` or `reference_repo/dcd-server` unless the
task explicitly calls for those private checkouts.

### 2. Create a virtual environment

`dcd-cli` requires Python 3.13+.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 3. Install `dcd-cli`

Follow the upstream installation instructions in `reference_repo/dcd-cli/README.md`.

Example:

```bash
pip install git+https://github.com/dataclawdev/dcd-cli.git
```

### 4. Create local config

```bash
cp .server_info.example .server_info
source .server_info
```

This repo uses `DCD_TOKEN` in `.server_info`. Some `dcd-cli` docs and examples still use
`DCD_SECRET`, so map it when needed:

```bash
export DCD_SECRET="$DCD_TOKEN"
```

Do not commit real tokens, passwords, or personal credentials.

### 5. Run a pipe test

```bash
pytest -q pipelines/<family>/<pipe_name>/tests
```

Example:

```bash
pytest -q pipelines/wiki/stage2_parse_html/tests
```

### 6. Validate a pipe

```bash
dcd pipe validate pipelines/<family>/<pipe_name> --host "$DCD_HOST"
```

Example:

```bash
dcd pipe validate pipelines/wiki/stage2_parse_html --host "$DCD_HOST"
```

## What To Read Next

- For pipe authoring and runtime semantics, start with `reference_repo/dcd-cli/docs/pipe.md`.
- For CLI behavior such as `register`, `update`, `fetch`, and `validate`, see
  `reference_repo/dcd-cli/docs/cli.md`.
- For text format conventions such as `html`, `markdown`, `json`, and `openai`, see
  `reference_repo/dcd-cli/docs/text-formats.md`.
- For local viewer work, use `skills/dcd-local-server/SKILL.md`; if you have access to the
  private `reference_repo/dcd` checkout, its viewer docs can be used as optional background.
- For agent-specific execution rules in this repo, see `AGENTS.md`.

## Upstream repos (how they relate)

- **`dcd-cli`** — Canonical docs and behavior for pipe manifests, CLI usage, and validation.
- **`dcd-server`** — Optional private server-side reference. Use it only when the task explicitly
  needs server implementation details and your local checkout is available.
- **`dcd`** — Optional private full-stack/local-viewer reference. Use it only when the task
  explicitly needs local UI implementation details and your local checkout is available.

## Repo Layout

- `pipelines/`
  Deployable pipeline packages. Preferred layout:
  `pipelines/<family>/<pipe_name>/`
- `reference_repo/`
  Reference repos managed as git submodules. `dcd-cli` is the required pipe contract; `dcd` and
  `dcd-server` are optional private references and do not need to be initialized.
- `skills/`
  Agent-oriented workflow docs
- `workspace/`
  Repo-local area for temporary datasets, logs, local viewer state, screenshots, and other
  developer-only runtime artifacts

`workspace/` is usually not tracked by git and may not exist in a fresh clone. Create it only
when needed:

```bash
mkdir -p workspace
```

## Pipe Package Expectations

Each deployable pipe should usually stay self-contained and include:

- `manifest.yaml`
- `__init__.py` or `main.py`
- `requirements.txt`
- `README.md`
- `tests/`

In practice:

- `manifest.yaml` defines the pipe metadata and runtime config schema.
- The entry module implements the function matching the declared operation, such as
  `map()`, `filter()`, `expand()`, `reduce()`, or `ingest()`.
- Tests should run in isolation without depending on developer-specific absolute paths.
- When behavior changes, update implementation, `manifest.yaml`, tests, and the pipe-local
  `README.md` together.

## Local DCD Viewer

The local browser UI does not live in `dcd-cli`. Older setups used `reference_repo/dcd`, but that
upstream can be private and is optional in this workspace.

Keep in mind:

- the active DCD server determines which dataset directory is visible in the UI
- files under `workspace/` are local developer artifacts, not automatic live UI config
- for a standard agent workflow around the local server, see `skills/dcd-local-server/SKILL.md`
