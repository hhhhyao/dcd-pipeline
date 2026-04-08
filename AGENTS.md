# AGENTS.md

## Project Overview

`dcd_pipeline` is a repository for developing, testing, and maintaining DCD pipelines.

Treat this repo as a general pipeline-development workspace. The checked-in `pipelines/wiki/` tree is a useful example, not the only valid pattern or business domain.

## Read These First

When you work on a pipe, use `reference_repo/dcd-cli` as the primary source of truth for package structure, manifest semantics, runtime expectations, and validation.

Recommended reading order:

1. `reference_repo/dcd-cli/docs/pipe.md`
   Authoritative pipe authoring guide: layout, manifest fields, operations, config, resources, network, Python version, runtime sandbox, volumes, and testing concepts.
2. `reference_repo/dcd-cli/docs/cli.md`
   CLI behavior for `dcd pipe register`, `update`, `fetch`, and `validate`.
3. `reference_repo/dcd-cli/docs/text-formats.md`
   Use this whenever a pipe reads or writes text formats such as `html`, `markdown`, `json`, or `openai`.
4. `reference_repo/dcd-cli/README.md`
   Quick reference for package shape, `PipeContext`, manifest examples, and helper utilities.
5. `reference_repo/dcd-cli/pipe-demos/*/README.md`
   Concrete examples for ingest and transform pipes. Prefer demos that match the operation or modality you are implementing.
6. `reference_repo/dcd-cli/skills/user/update-pipe/SKILL.md`
   Useful agent-oriented checklist, but treat the docs above as the normative interface reference.

## Environment

- Use a dedicated Python virtual environment.
- Initialize submodules before doing validation or implementation work:

```bash
git submodule update --init --recursive
```

- Reference repos live in:
  - `reference_repo/dcd`
  - `reference_repo/dcd-cli`
- Local secrets belong in `.server_info`, created from `.server_info.example`.
- Never commit real tokens, passwords, or personal credentials.

## Config and Auth

This repo's local template uses `DCD_TOKEN` in `.server_info`.

Some `dcd-cli` docs and commands still refer to `DCD_SECRET`. When you need CLI compatibility, export the value explicitly in your shell before running commands that expect `DCD_SECRET`.

Example:

```bash
export DCD_HOST="..."
export DCD_SECRET="$DCD_TOKEN"
```

Do not rewrite committed docs just to preserve both naming schemes unless the task explicitly requires compatibility aliases.

## Directory Map

- `pipelines/`
  Deployable pipeline packages. Preferred layout is `pipelines/<family>/<pipe_name>/`.
- `skills/`
  Source-of-truth skill docs for agent workflows in this repo.
- `reference_repo/`
  Submodule-managed upstream references.

## Pipe Package Rules

Each deployable pipe should stay self-contained and usually include:

- `manifest.yaml`
- `__init__.py` or `main.py`
- `requirements.txt`
- `README.md`
- `tests/`

Follow these rules when editing or creating a pipe:

- Keep pipe names valid Python package names: lowercase letters, digits, and underscores; start with a letter.
- Keep runtime logic inside the pipe package, not in repo-root helper glue.
- Update `manifest.yaml`, implementation, tests, and local pipe docs together when behavior changes.

## Testing Rules

Tests for an active pipe should be runnable in isolation.

Prefer:

- package-local imports
- fixture files under the pipe's own `tests/fixtures/`
- commands scoped to a single pipe directory

Avoid:

- repo-root absolute paths
- test setup that depends on a specific developer machine layout
- hidden coupling to unrelated pipeline families

Typical command:

```bash
pytest -q pipelines/<family>/<pipe_name>/tests
```

Example:

```bash
pytest -q pipelines/wiki/stage3_parse_html/tests
```

## Validation Workflow

For pipe-level validation, use `dcd-cli` against the specific directory you changed.

```bash
python3 -m dcd_cli.cli pipe validate pipelines/<family>/<pipe_name> --host "$DCD_HOST"
```

If you are preparing a new version, also review the corresponding upload/update flow in `reference_repo/dcd-cli/docs/cli.md` before changing manifests or release notes.

## Documentation Expectations

- Root `README.md` is human-facing and should stay concise, general, and high-signal.
- Root `AGENTS.md` is agent-facing and should stay procedural, implementation-oriented, and repo-specific.
- `skills/` contains the authoritative agent workflows for this repo.
- Pipeline-local `README.md` files should describe the pipe's actual input/output, config, and behavior.

## Style and Safety

- Prefer small, composable Python helpers and explicit names.
- Preserve ASCII unless a file already requires non-ASCII.
- Avoid printing secrets in commands, logs, test fixtures, or docs.
- If local config keys need to change, preserve user values when possible.
- When a requirement is ambiguous, prefer the `dcd-cli` docs over project-specific habit.
