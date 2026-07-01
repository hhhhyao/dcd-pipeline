---
name: dcd-pipe-debug-iteration
description: "Use when running a traceable, multi-round debug and refinement workflow for a DCD data processing pipe: diagnose outputs, split bad-case datasets for DCD review, collect human-confirmed issues, add minimal regression tests, patch the pipe, rerun local and remote validation, document each round, and preserve rollback points."
---
# DCD Pipe Debug Iteration

## Purpose

Use this skill for long-running pipe refinement where correctness must be improved through
diagnosis, human review, regression tests, local iteration, and DCD server validation.

The goal is not only to fix a bug. The goal is to leave behind:

- a refined pipe
- a representative regression test suite
- traceable diagnostic reports and bad-case datasets
- clear round-by-round change docs
- commit or tag points that make rollback straightforward

## Read First

For DCD semantics and repo rules, read:

1. `AGENTS.md`
2. `reference_repo/dcd-cli/docs/pipe.md`
3. `reference_repo/dcd-cli/docs/cli.md`
4. Pipe-local `README.md`, `manifest.yaml`, and tests

When uploading pipes, running jobs, inspecting datasets, or managing DCD projects/resources,
also use the repo skill `skills/dcd-server-operations/SKILL.md`.

For adjacent repeatable workflows, use:

- `skills/dcd-fetch-review-issues/SKILL.md` when pulling human-confirmed DCD
  issues into a local debug cache.
- `skills/dcd-upload-hf-lance-dataset/SKILL.md` when exporting a review subset
  through Hugging Face and importing it into DCD.

## Core Principles

- Keep each iteration focused on one issue family unless the user explicitly asks to bundle fixes.
- Treat detector output as a triage signal, not ground truth. Human confirmation and regression tests define the real target behavior.
- Use a manageable initial iteration dataset. Prefer 10k-50k input rows; if the source is much larger, ask the user whether to sample or stratify before starting broad diagnosis.
- When debugging one stage inside a pipeline, diagnose against the previous stage's output unless the user explicitly wants a different input boundary.
- Prefer minimal fixtures that preserve the root cause. If minimization would hide the bug, use the full bad sample.
- When several bad cases share one root cause, add one representative test, not many duplicates.
- Every behavioral pipe change needs a test or a documented reason why a test is impractical.
- Every server-side review dataset must identify the source dataset, pipe version, diagnosis run, and issue type.
- Keep DCD pipe and output dataset names stable across iterations whenever possible. Stable names
  make server-side versions and human review history easier to follow.
- Preserve rollback points with commits, tags, or at minimum named patch docs tied to the current git hash.

## Standard Artifacts

Create all per-project iteration state under:

```text
workspace/pipe-debug/<project_name>/
  README.md or TRACKING.md
  docs/
    baseline_<date>.md
    issue_<issue_type>.md
    milestone_<nn>_<issue_type>.md
  scripts/
    diagnose_<project_name>.py
    export_issue_dataset.py
    run_badcase_regression.py
  datasets/
    source_sample_manifest.json
    subset_<issue_type>_<round>.json
  pipes/
    debug_<pipe_name>/  # copy or symlink used for DCD debug uploads
    debug_<pipe_name>_filter_<filter_process_name>/  # short-lived filter pipe
      id_lists/
  issues/
  jobs/
```

Create a new `<project_name>` folder for each larger pipe iteration effort, such as one pipe
plus several related issue families. All later scripts, reports, issue caches, review dataset
manifests, and job records for that effort should live under that folder.

Use pipe-local tests for regression fixtures:

```text
pipelines/<family>/<pipe_name>/tests/
  test_<issue_type>_regressions.py
  fixtures/
```

Do not put runtime logic in repo-root helpers when it belongs inside the pipe.
Debug scripts may orchestrate diagnosis and dataset export, but pipe behavior belongs in the
pipe package.

For DCD upload, use stable debug names for the whole pipe refinement effort. The human-facing
pattern is:

- DCD project: `debug-<pipeline>`; confirm with the user when the pipeline name is ambiguous.
- Main debug pipe: `debug-<pipe-name>`.
- Related filter pipe: `debug-<pipe-name>-filter-<filter-process-name>`.
- Baseline review output dataset after filtering:
  `debug-<pipe-name>-filter-<filter-process-name>-baseline`.
- Fix review output dataset for later repaired pipe versions:
  `debug-<pipe-name>-filter-<filter-process-name>-fix`.

Because current DCD pipe manifests require valid Python package names, normalize those names in
`manifest.yaml` by replacing hyphens with underscores, for example:

- `debug_wiki_html_to_md`
- `debug_wiki_html_to_md_filter_footer_selected_as_content`

Dataset names are not Python package names. Prefer the hyphenated dataset naming pattern above
when the DCD server accepts it; if an environment normalizes dataset names, record the exact
server name and the human-facing name in the version trace.

Keep the server pipe name stable and update the same pipe across rounds. If changing
`manifest.yaml` would create noisy git changes in the real pipe, create a copy or symlink under
the project `pipes/` directory and change the manifest there before upload. At the start of an
effort, check whether the debug pipe already exists on DCD; if it exists, update it instead of
registering a new name.

For issue subsets, prefer a short-lived debug filter pipe under the project `pipes/` directory.
This pipe is only for debugging and review, not for production. It can bundle small or medium ID
lists as JSON files under `id_lists/` so both local runs and the server-side sandbox can read
them from the pipe package.

Whenever a DCD project exists for the effort, add newly uploaded debug pipes, filter pipes, output
datasets, and relevant jobs to that project immediately. Use
`skills/dcd-server-operations/SKILL.md` for the exact API flow and remember that project API
paths use the project slug, not display name.

## Workflow

### 0. DCD Project Setup

When the iteration will use DCD for visualization, server-side pipe runs, or human review:

1. Confirm or create one DCD project for the effort. Prefer display name/pattern
   `debug-<pipeline>` unless the user provides an existing project.
2. Record both project display name and project slug. API calls must use the slug.
3. Add the source/sample dataset to the project if it is not already there.
4. Check whether the stable main debug pipe already exists. Register it if missing; otherwise
   update it.
5. For every later DCD upload or run, add the new or updated resource to the project:
   - source/sample dataset
   - issue subset dataset
   - baseline review output dataset
   - fix review output dataset
   - residual subset dataset
   - main debug pipe
   - filter pipe
   - validation job
   - human-confirmed issue
6. Record project resource API responses or snapshots under the project `jobs/` or `docs/`
   directory so membership changes are traceable.

Use `skills/dcd-server-operations/SKILL.md` for project APIs and server access checks.

### 1. Establish Baseline

Before changing the pipe:

1. Record the source dataset path or DCD dataset name.
2. If the pipe is one stage in a pipeline, identify the previous stage dataset and confirm that
   it is the intended input for this iteration.
3. Record dataset row count. If it is outside the 10k-50k range for local iteration, propose a
   deterministic sample or stratified sample and get user confirmation when the choice affects
   coverage.
4. Record the pipe path, manifest version, and current git hash.
5. Locate or run the diagnosis report.
6. If no diagnosis script exists, create an initial diagnosis script first. It may start from
   user descriptions, DCD issues, manual samples, or simple output heuristics, but it must emit
   machine-readable bad-case rows before implementation begins.
7. Save aggregate counts by issue type.
8. Save full bad-case rows with sample IDs, issue labels, detector details, and snippets.
9. Write a baseline doc that links to all generated artifacts.

The baseline doc should answer:

- Which data was diagnosed?
- If the pipe is a pipeline stage, which previous-stage dataset was used?
- Was the dataset sampled? If yes, how?
- Which pipe produced the output?
- Which detector rules were used?
- What issue categories were found?
- Where is the full sample ID list?
- What is the DCD project display name and slug?
- What is the DCD debug pipe name?
- What naming convention will issue filter pipes use?
- Where is the project root under `workspace/pipe-debug/`?

### 1.5. Bootstrap Diagnosis When Missing

When the iteration starts from user descriptions, DCD issues, or ad hoc observations rather
than an existing detector:

1. Pull any DCD issues or manually supplied sample IDs.
2. Inspect representative input/output pairs.
3. Write a first-pass diagnosis script under the project `scripts/` directory.
4. Make the script emit JSON/JSONL with sample ID, issue type, evidence, snippet, and detector
   version.
5. Run it on the initial iteration dataset.
6. Treat its output as provisional until human review confirms the issue type.

Do not jump directly from a verbal symptom to broad pipe edits unless the user explicitly asks
for a quick one-off fix.

### 2. Create Or Update Issue Subsets

Upload the sampled previous-stage source dataset once for the project when DCD visualization is
needed. Then derive issue-specific review subsets with a debug filter pipe instead of repeatedly
uploading many local datasets.

The same filter pipe may also be run locally to generate Lance subsets under the project
`datasets/` directory. Prefer local filtering for fast iteration and DCD filtering for human
visual review.

Recommended flow:

1. Upload or identify one stable sampled source dataset from the previous pipeline stage.
2. Create a short-lived filter pipe under
   `workspace/pipe-debug/<project_name>/pipes/debug_<pipe_name>_filter_<filter_process_name>/`.
   Use the same normalized name in the filter pipe manifest.
3. Put the issue or residual ID list into the filter pipe package, for example
   `id_lists/footer_round01_initial.json`.
4. Run the filter pipe locally or on DCD against the stable sampled source dataset to create an
   issue subset dataset.
5. Add diagnosis metadata to the front of the sample `info` field or equivalent metadata field.
6. Preserve original identifiers and source pointers.
7. If run on DCD, add the filter pipe, output dataset, and job to the DCD project.
8. Record filter pipe name/version or local git hash, ID list file, ID list hash, source dataset,
   output subset dataset, row count, job ID when applicable, and diagnosis artifact.

After the issue subset exists on DCD, run the current iteration pipe on that filtered dataset
before asking for human review. This produces the first reviewable output for the issue family:

```text
debug-<pipe-name>-filter-<filter-process-name>-baseline
```

Use the pipe version that represents the current baseline for the issue. If some local edits
already exist before the formal loop starts, document whether the DCD baseline uses the server's
existing debug pipe version or a newly uploaded copy of the current local code.

For later repair iterations, run updated pipe versions against the same filtered issue subset and
write to:

```text
debug-<pipe-name>-filter-<filter-process-name>-fix
```

Reuse this `-fix` dataset name across repair rounds so DCD dataset versions capture each fix
attempt. Record the job id, output dataset version, debug pipe version, git hash, and config for
every `-baseline` and `-fix` run. Add both output datasets and all jobs to the DCD project.

Use `skills/dcd-upload-hf-lance-dataset/SKILL.md` only when a local Lance dataset itself needs
to be uploaded/imported. For issue subsets, prefer running the filter pipe on DCD once the source
sample dataset is already available there.

For short-lived debug filter pipes, the bundled ID-list mode is usually best:

```text
workspace/pipe-debug/<project_name>/pipes/debug_<pipe_name>_filter_<filter_process_name>/
  manifest.yaml
  __init__.py
  id_lists/
    footer_round01_initial.json
    footer_round02_residual.json
```

The filter pipe should support config such as:

```json
{
  "id_list_file": "footer_round01_initial.json",
  "issue_type": "footer_selected_as_content",
  "diagnosis_run": "20260504_baseline",
  "metadata_prefix": true
}
```

This is appropriate when ID lists are small or medium sized and the filter pipe is not intended
to be long-lived. The bundled JSON becomes part of the DCD filter pipe version, which makes the
subset reproducible and reviewable. If an ID list is very large, prefer tagging the source
dataset `info` or another scalable source-specific approach.

For local runs, write the output dataset under:

```text
workspace/pipe-debug/<project_name>/datasets/<issue_type>_<round>/
```

and write the subset manifest beside it, for example:

```text
workspace/pipe-debug/<project_name>/datasets/subset_<issue_type>_<round>.json
```

Local subset generation should preserve the same metadata and ID-list hash recorded for DCD
runs, so local and server outputs can be compared.

Recommended subset manifest:

```json
{
  "subset_name": "...",
  "issue_type": "...",
  "subset_round": 1,
  "source_dataset": "...",
  "source_dataset_version_or_run": "...",
  "filter_pipe": "debug_<pipe_name>_filter_<filter_process_name>",
  "filter_pipe_version": 1,
  "filter_pipe_local_git_hash": "...",
  "execution_location": "local|dcd",
  "filter_mode": "bundled_id_list",
  "id_list_file": "id_lists/footer_round01_initial.json",
  "id_list_sha256": "...",
  "diagnosis_artifact": "...",
  "output_dataset": "...",
  "output_dataset_version_or_run": "...",
  "job_id": 0,
  "row_count": 0
}
```

Recommended metadata keys inserted into each selected row:

```json
{
  "diagnosis_issue_type": "...",
  "diagnosis_run": "...",
  "diagnosis_detector": "...",
  "diagnosis_subset_round": 1,
  "source_dataset": "...",
  "source_sample_id": "...",
  "filter_pipe": "...",
  "filter_pipe_version": "...",
  "filter_id_list_file": "...",
  "pipe_path": "...",
  "pipe_git_hash": "..."
}
```

During one issue's iteration, repeat this subset loop as needed:

```text
source sample dataset
  -> filter pipe + bundled initial id list
  -> issue subset
  -> debug pipe baseline run
  -> DCD human review on baseline dataset
  -> local fixes
  -> debug pipe fix run
  -> DCD human review on fix dataset
  -> diagnosis of remaining failures
  -> filter pipe + bundled residual id list
  -> smaller residual subset
  -> next baseline/fix review loop when needed
```

Keep source dataset names and repeated debug output dataset names stable inside one debug loop
when doing so helps DCD track versions/runs. Add explicit round suffixes only when stable reuse
would make human review ambiguous.

### 3. Human Confirmation Gate

Do not start a broad fix only from aggregate counts. First determine:

- Which samples are real bugs?
- Which samples are detector false positives?
- Which samples belong to a different issue type?
- Which examples best represent distinct root causes?

If the user records confirmed cases in DCD issues, pull or summarize those issue records before
implementation.

Use `skills/dcd-fetch-review-issues/SKILL.md` for the issue-pull flow and link the resulting
cache in the round doc.

### 4. Local Fix Loop

For one selected issue family:

1. Inspect confirmed bad cases.
2. Group cases by root cause.
3. For each root cause, create the smallest fixture that still reproduces the bug.
4. Add or update regression tests and confirm they fail on the current code when practical.
5. Patch the pipe with the narrowest change that matches existing pipe style.
6. Run pipe-local tests.
7. Run the bad-case regression script for the current issue subset.
8. Inspect remaining failures.
9. When a repair is ready for human review, upload/update the stable debug pipe and run it on
   the filtered issue subset, writing to the stable `-fix` output dataset for that issue/filter.
   Let DCD dataset versions distinguish rounds.
10. When useful for DCD visualization or human review, generate a residual ID list and update the
   debug filter pipe to create a smaller residual subset.
11. If local diagnosis or regression is slow enough to interrupt iteration, optimize the runner or
   switch to a faster validation strategy before continuing broad debugging.
12. Repeat until remaining cases are false positives, different issue families, or require a broader design decision.

Keep tests focused on behavior, not implementation details. Good assertions usually check:

- expected output is present
- known bad output is absent
- metadata or IDs needed by downstream stages are preserved
- unrelated formatting remains stable enough for downstream consumers

Local speed work may include batching, multiprocessing, avoiding repeated Lance scans, caching
source rows by ID, running detectors only on affected issue subsets, or adding a fast smoke set
before the full bad-case regression. Do not optimize production pipe behavior just to speed a
debug script unless the same bottleneck affects the real pipe.

### 5. Documentation

Keep documentation traceable but not too fragmented. Use three levels:

1. `README.md` or `TRACKING.md`: project index, stable names, current status, and links.
2. `docs/issue_<issue_type>.md`: one living document per problem type. Append local rounds here.
3. `docs/milestone_<nn>_<issue_type>.md`: detailed report for each DCD human-validation point
   or other major checkpoint.

Use Chinese for reports and docs when the user is supervising in Chinese. Be explicit and
detailed enough for human validation: describe what changed, why it changed, how it was tested,
and what remains uncertain.

For each local round inside `issue_<issue_type>.md`, append a compact section:

```markdown
## Local Round <N>

- 时间:
- 起始 git hash:
- 结束 git hash:
- 触发样本/issue:
- root cause:
- 新增/修改测试:
- 修改文件:
- 本地命令与结果:
- bad-case 回归结果:
- 剩余问题:
```

For each server validation or major checkpoint, create a milestone report:

```markdown
# Milestone <N>: <Issue Type>

## Scope
- Pipe:
- DCD debug pipe:
- DCD pipe version:
- Pipeline stage/input boundary:
- Source dataset:
- Iteration dataset/sample:
- Review dataset:
- Baseline output dataset/version:
- Fix output dataset/version:
- Subset manifest:
- Filter pipe/version:
- Filter ID list/hash:
- Diagnosis artifact:
- Starting git hash:
- Ending git hash:

## Confirmed Symptoms
- Sample IDs:
- User/DCD confirmation:
- Detector evidence:

## Root Causes
- ...

## Changes
- Files changed:
- Behavior changed:
- Behavior intentionally unchanged:

## Tests
- Added/updated tests:
- Commands run:
- Results:

## Local Rounds
- Round summary:
- Detailed issue doc:

## Bad-Case Regression
- Before:
- After:
- Remaining failures:
- Runtime/performance notes:

## Residual Subset
- Residual ID list:
- Filter pipe/version:
- Output subset dataset:
- Job/result:

## Server Review
- Uploaded debug pipe/version:
- DCD baseline job:
- Baseline output dataset/version:
- DCD fix job:
- Fix output dataset/version:
- Human review result:

## Rollback
- Commit/tag to revert to:
- Notes:
```

If a section is not yet applicable, write `Not run` or `Pending` rather than leaving ambiguity.

### 6. DCD Validation Gate

When local tests and bad-case regression are good enough:

1. Validate the pipe package.
2. Upload or update the stable `debug-<pipe-name>` pipe on DCD, normalized to
   `debug_<pipe_name>` in the manifest when required by DCD naming rules.
3. For issue-family review, run it against the filtered issue subset rather than the broader
   source dataset unless the goal is broad regression.
4. For the first review run on a filtered subset, write to:
   `debug-<pipe-name>-filter-<filter-process-name>-baseline`.
5. For repaired versions, write to:
   `debug-<pipe-name>-filter-<filter-process-name>-fix`.
6. Reuse the same `-fix` dataset name across repair rounds so DCD dataset versions track the
   iteration history.
7. Record the job ID, output dataset, observed dataset version, pipe slug/version, config, and
   git hash.
8. Add the output dataset and validation job to the DCD project.
9. Wait for human review before moving to the next issue family when the user wants supervision.

### 7. Move To Next Issue

Close an issue family only when:

- representative tests exist for the fixed root causes
- the targeted bad-case subset has been rerun locally
- the server `-baseline` and latest `-fix` outputs have named dataset versions or job records
- remaining failures are listed and classified
- docs identify the exact pipe version reviewed

Then repeat the process for the next issue family.

## Versioning And Rollback

Prefer one branch per larger refinement effort and one commit per coherent round.

Suggested naming:

```text
debug-<pipe-name>
debug-<pipe-name>-filter-<filter-process-name>
debug-<pipe-name>-filter-<filter-process-name>-baseline
debug-<pipe-name>-filter-<filter-process-name>-fix
```

Use the same DCD debug pipe name for the whole refinement of one pipe. Use one stable filter
pipe name per filter process, such as one issue-family subset selector. Use one stable
`-baseline` dataset for the pre-fix/current-state review and one stable `-fix` dataset for
repair review rounds. Version changes should be tracked through DCD pipe versions, DCD dataset
versions, git hashes, and milestone docs, not by changing names each round.

Before risky changes, record:

```bash
git status --short
git rev-parse HEAD
```

Never revert unrelated user changes. If unrelated dirty files exist, document them and keep
edits scoped.

## Expected Final Response

When reporting progress to the user, include:

- current issue family
- project root under `workspace/pipe-debug/`
- artifacts created or updated
- tests and diagnosis commands run
- current counts before/after
- local runtime if it affects iteration speed
- remaining bad cases or blockers
- exact next recommended step

Keep the report compact, but make paths and versions concrete.
