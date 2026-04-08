# pipelines/wiki

`pipelines/wiki` contains the active DCD wiki pipeline implementation.

## Active Stages

- `stage0_ingest_jsonl_tar_to_html`
- `stage1_html_localize_image_ids`
- `stage3_parse_html`
- `stage4_md_to_openai`

## Notes

- `stage1` localizes HTML image references using the existing row-level image IDs.
- The previous split `stage1` / `stage2` flow has been archived into `old_pipelines/` and is no longer part of the tracked mainline.
- Active stage names do not use the `_lance` suffix anymore.

## Layout

- `stage*/`
  Deployable pipe packages with code, manifest, requirements, docs, and tests.
- `run_local/`
  Local execution helpers kept outside deployable pipe directories.
- `upload_pipe.sh`
  Helper for validating and uploading a local pipe to a DCD server.
