# stage1_html_localize_image_ids

Stage 1 rewrites wiki HTML image URLs to dataset-local `images/<id>` refs and
deduplicates `images.lance` / `image_labels.lance`.

The input dataset is resolved from framework context:

- `ctx.volumes["dataset"]` if present
- otherwise `/datasets/<ctx.dataset>`

Expected input tables:

- `text.lance`
- `images.lance`
- `image_labels.lance`

Outputs written to `ctx.output_dir`:

- `text.lance`
- `images.lance`
- `image_labels.lance`
- `image_url_missing.jsonl`
- `image_id_unmatched_warning.jsonl`
- `dataset.yaml`
- `run_info.yaml`

Behavior:

1. Read Stage-0 raw HTML rows and per-row `info.image_ids`
2. Load candidate original image URLs from `image_labels.lance`
3. Rewrite matching HTML `<img src=...>` to `images/<id>`
4. Keep warning artifacts for missing HTML URLs / unmatched image IDs
5. Deduplicate `images.lance` and `image_labels.lance` by image ID

Common config keys:

- `cache_dir`
- `batch_size`
- `write_flush_rows`
- `progress_every`
- `extractor`
- `normalizer`
- `formatter`
- `rewriter`
- `compact_tables`
- `overwrite`
