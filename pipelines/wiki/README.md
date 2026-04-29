# pipelines/wiki

`pipelines/wiki` contains the active DCD wiki pipeline implementation.

## Active Stages

- `stage0_ingest_jsonl_tar_to_html`
- `stage0_5_import_hf_stage0` (optional)
- `stage0_5_import_hf_lance_dataset` (optional, generic HF Lance import)
- `stage1_html_localize_image_ids`
- `stage1_5_merge_datasets_zero_copy` (optional)
- `stage2_parse_html`
- `stage3_md_to_openai`
- `stage4_filter_images`

## Notes

- `stage0` ingests raw `part*.jsonl + part*.tar` into an HTML Lance dataset using
  content-stable SHA256 article/image IDs.
- `stage0_5` imports a locally generated Stage0 Lance dataset that was uploaded
  directly to a Hugging Face dataset repo. It is a server-side transport/import
  bridge, not a transformation stage.
- `stage0_5_import_hf_lance_dataset` is the generic Hugging Face Lance import
  bridge for already-materialized wiki Lance datasets. It supports row-order
  image/image-label pairing for raw Stage0-style datasets and id-join pairing
  for deduplicated Stage1-style datasets.
- `stage1` rewrites HTML image references to dataset-local `images/<id>` refs and
  deduplicates `images.lance` / `image_labels.lance`.
- `stage1_5` merges multiple completed Stage1 datasets before continuing to
  Stage2.
- `stage2` parses cleaned HTML into markdown (default) or simplified HTML.
- `stage3` converts cleaned markdown into OpenAI-style multimodal content blocks.
- `stage4` filters OpenAI image blocks by width/height metadata only.
- Older experimental wiki pipes (including a previous multi-stage split) live under
  `old_pipelines/` and are not part of the active sequence above.
- Active stage names do not use the `_lance` suffix anymore.

Recommended sequence:

```text
stage0 -> optional stage0_5 -> stage1 -> optional stage1_5 -> stage2 -> stage3 -> stage4
```

Use `stage0_5` when Stage0 was run locally and the resulting `text.lance/`,
`images.lance/`, and `image_labels.lance/` directories were uploaded to
Hugging Face for server-side import. Skip it when Stage0 already ran on the
target DCD server. Use `stage0_5_import_hf_lance_dataset` when importing a
locally produced Lance dataset from Hugging Face and you need to choose between
`row_order` and `id_join` image pairing. Use `stage1_5` only when several Stage1
outputs need to be combined before Stage2.

## Layout

- `stage*/`
  Deployable pipe packages with code, manifest, requirements, docs, and tests.
- `run_local/`
  Local execution helpers kept outside deployable pipe directories.
- `upload_pipe.sh`
  Helper for validating and uploading a local pipe to a DCD server.
