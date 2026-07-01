---
name: dcd-upload-hf-lance-dataset
description: Use when uploading a local Lance dataset to a Hugging Face dataset repository and creating a DCD import job, especially for review subsets or bad-case datasets that need to be visible on a DCD server.
---
# DCD Upload HF Lance Dataset

## Purpose

Use this skill when a local Lance dataset must be made visible on a DCD server by uploading it
to Hugging Face and running a DCD import pipe.

This is useful for:

- bad-case review datasets
- issue-specific subsets
- before/after validation outputs
- any small or medium Lance dataset that should be inspected in DCD frontend

## Required Inputs

- local dataset directory containing `text.lance`
- Hugging Face dataset repo ID, for example `owner/name`
- DCD output dataset name
- DCD host and token from `.server_info` or environment
- import pipe slug and version
- whether to include images
- whether the HF repo should be public or private

For text+image Lance datasets, also confirm whether images are paired by `id_join` or
`row_order`.

## Preflight Checks

1. Verify the local dataset exists and contains `text.lance`.
2. If importing images, verify `images.lance` and `image_labels.lance` exist.
3. Verify Hugging Face auth with `huggingface-cli whoami`.
4. Read `.server_info` for `DCD_HOST` and `DCD_TOKEN`; if needed, map
   `DCD_SECRET="$DCD_TOKEN"`.
5. Confirm the DCD import pipe exists and supports the dataset layout.
6. Confirm the requested DCD output dataset name and import parameters for this task.
7. Record the current git hash and source dataset path before uploading.

## Recommended DCD Import Pipe

The successful path in this repo used:

```text
stage0_5_import_hf_lance_dataset
```

For Stage1+ wiki-style datasets, use:

```json
{
  "image_pairing_mode": "id_join",
  "include_text": true,
  "include_images": true,
  "validate_duplicate_image_ids": true
}
```

Use `row_order` only for datasets where image rows and labels are intentionally aligned by row
position.

Private Hugging Face repos require a DCD user secret named `HF_TOKEN` at job runtime. If that
secret is not configured, use a public HF dataset repo for review subsets.

## Workflow

1. Create or update the HF dataset repo.
2. Upload the full local dataset directory to the repo root, unless a `dataset_subdir` is
   intentionally used.
3. Create a DCD job whose step runs the HF Lance import pipe.
4. Set `input_dataset` to an empty string for ingest-style import jobs.
5. Set `output_dataset` to the desired DCD dataset name.
6. Poll the job when the user needs confirmation in the same turn.
7. Save a result JSON with local path, HF repo, job response, final status, and output dataset.
8. Verify row counts on DCD when possible.

Use the repo-level tool script:

```bash
python3 tools/dcd_debug/upload_hf_lance_dataset.py \
  --local-dataset workspace/<project>/<local_dataset> \
  --hf-repo <owner>/<hf_dataset_repo> \
  --dcd-output-dataset <dcd_dataset_name> \
  --public \
  --poll \
  --result-json workspace/<project>/<import_job_result>.json
```

The project-specific script that previously worked was:

```bash
python3 debug/stage2_bad_case_dataset/upload_hf_create_dcd_job.py \
  --local-dataset workspace/wiki_0320_en_has_pic/html_lance/wiki_0320_en_has_pic_20260429_stage1_badcases \
  --hf-repo lewei123/wiki_0320_en_has_pic_20260429_stage1_badcases \
  --dcd-output-dataset wiki_0320_en_has_pic_20260429_stage1_badcases \
  --public \
  --poll \
  --result-json workspace/wiki_0320_en_has_pic/stage1_badcases_import_job_20260429.json
```

Treat that as a historical example. Prefer the `tools/dcd_debug/` script for new projects.

## Result Record

Always save a machine-readable result file, for example:

```json
{
  "local_dataset": "...",
  "hf_repo": "...",
  "dcd_output_dataset": "...",
  "dcd_host": "...",
  "pipe_slug": "...",
  "pipe_version": 1,
  "job_id": 1380,
  "final_status": "done",
  "git_hash": "..."
}
```

Do not include tokens.

## Troubleshooting

- **`text.lance not found`**: point `--local-dataset` at the dataset root, not at
  `text.lance` itself.
- **HF auth fails**: run `huggingface-cli whoami`; log in outside the script if needed.
- **HF repo exists with stale files**: overwrite by uploading the full folder, or use a new repo
  name for immutable review snapshots.
- **Private HF repo fails on DCD**: configure server-side `HF_TOKEN`, or rerun with a public repo.
- **DCD host/token missing**: read `.server_info`; accept either `DCD_TOKEN` or `DCD_SECRET`.
- **Import pipe slug/version not found**: validate the pipe exists on the target server and
  update the slug or version.
- **Duplicate image ID validation fails**: inspect duplicates and hashes; fix the dataset when
  possible. Disable validation only for exploratory imports and document it.
- **Wrong image pairing**: use `id_join` for Stage1+ deduplicated images; use `row_order` only
  for raw row-aligned snapshots.
- **Job times out while polling**: save the job ID and result JSON; the server job may continue.
- **Dataset name collision**: confirm the intended output dataset name and overwrite/version
  behavior for the current task before rerunning.
- **Large dataset upload is slow**: test with a small subset first; keep batch sizes conservative
  for import jobs.

## Expected Report

When finished, report:

- local dataset path
- HF repo
- DCD output dataset
- import pipe slug/version
- job ID and final status if polled
- row counts if verified
- result JSON path
- any remaining manual verification step
