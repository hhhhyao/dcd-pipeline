# pipelines/wiki

`pipelines/wiki` contains the active DCD wiki pipeline implementation.

## Active Stages

- `stage0_ingest_jsonl_tar_to_html`
- `stage1_html_localize_image_ids`
- `stage2_parse_html`
- `stage3_md_to_openai`
- `stage4_filter_images`

## Notes

- `stage0` ingests raw `part*.jsonl + part*.tar` into an HTML Lance dataset using
  content-stable SHA256 article/image IDs.
- `stage1` rewrites HTML image references to dataset-local `images/<id>` refs and
  deduplicates `images.lance` / `image_labels.lance`.
- `stage2` parses cleaned HTML into markdown (default) or simplified HTML.
- `stage3` converts cleaned markdown into OpenAI-style multimodal content blocks.
- `stage4` filters OpenAI image blocks by width/height metadata only.
- Older experimental wiki pipes (including a previous multi-stage split) live under
  `old_pipelines/` and are not part of the active sequence above.
- Active stage names do not use the `_lance` suffix anymore.

## Layout

- `stage*/`
  Deployable pipe packages with code, manifest, requirements, docs, and tests.
- `run_local/`
  Local execution helpers kept outside deployable pipe directories.
- `upload_pipe.sh`
  Helper for validating and uploading a local pipe to a DCD server.
