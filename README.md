# dcd_pipeline

`dcd_pipeline` is a workspace for developing, testing, and maintaining DCD pipelines.

The repo is not tied to a single business domain. The checked-in `pipelines/wiki/` tree is a
working example of how a pipeline family can be organized, tested, and run locally.

## Quick Start

Use this path if you just cloned the repo and want to get to a runnable setup quickly.

### 1. Initialize submodules

```bash
git submodule update --init --recursive
```

This repo depends on:

- `reference_repo/dcd`
- `reference_repo/dcd-cli`
- `reference_repo/dcd-server`

### Optional: Sync reference repos to upstream `main`

Submodules track `main` in `.gitmodules`. After init, or when you want the latest upstream:

```bash
git submodule update --remote --merge
```

Commit the updated submodule pointers in this repo if you want that revision recorded for others.

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
- For local viewer work, start with `reference_repo/dcd/README.md` and
  `reference_repo/dcd/docs/webapp.md`.
- For agent-specific execution rules in this repo, see `AGENTS.md`.

## Upstream repos (how they relate)

- **`dcd-cli`** — Canonical docs and behavior for pipe manifests, CLI usage, and validation.
- **`dcd-server`** — Server-side package from the same product line; prefer this checkout when you need **current** server/runtime code (HTTP stack, jobs, sandbox, and related `dataclawdev` implementation).
- **`dcd`** — Full monorepo (including frontend sources and local viewer docs). Use it for **full-stack local setup** narratives; if the upstream `dcd` checkout is stale or inaccessible, treat **`dcd-server`** as the fresher reference for **backend** behavior and keep **`dcd-cli`** as the pipe contract.

## Repo Layout

- `pipelines/`
  Deployable pipeline packages. Preferred layout:
  `pipelines/<family>/<pipe_name>/`
- `reference_repo/`
  Upstream reference repos managed as git submodules
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

The local browser UI lives in `reference_repo/dcd`, not in `dcd-cli`.

Keep in mind:

- the active DCD server determines which dataset directory is visible in the UI
- files under `workspace/` are local developer artifacts, not automatic live UI config
- for a standard agent workflow around the local server, see `skills/dcd-local-server/SKILL.md`
