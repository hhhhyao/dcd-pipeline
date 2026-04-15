# stage1_html_localize_image_ids

Production ingest pipe for wiki Stage 1.

This pipe rewrites HTML using `text.info.image_refs`. It does not read URL or
caption metadata from `image_labels.lance`.

## Input

The input dataset is resolved from the DCD pipe context:

- `ctx.volumes["dataset"]` when mounted.
- Otherwise `/datasets/<ctx.dataset>`.

Expected input tables:

- `text.lance`
- `images.lance`
- `image_labels.lance`

## Output

The pipe writes these artifacts to `ctx.output_dir`:

- `text.lance`
- `images.lance` as an absolute symlink to the source table
- `image_labels.lance`
- `image_url_missing.jsonl`
- `image_id_unmatched_warning.jsonl`
- `dataset.yaml`
- `run_info.yaml`

## Behavior

1. Read raw HTML rows and inline `info.image_refs` from `text.lance`.
2. Match HTML `<img src=...>` values against `image_refs[*].image_url_ori`.
3. Rewrite matched image tags to `src="images/<image_id>"` and add
   `_image_ref_id="<image_ref_id>"`.
4. Rewrite `info.image_ids` to the matched image ids while preserving
   `info.image_refs`.
5. Emit sidecar records for missing HTML URLs and unmatched or invalid image refs.
6. Link `images.lance` into the output directory without materializing image bytes.
7. Deduplicate `image_labels.lance` by `id`: first row wins for `info` and `data`,
   tags are merged in first-seen order, and non-tag content mismatches emit warnings.
8. Compact selected output tables. `images` is skipped because it is a symlink.

The rewritten `text.lance` and deduplicated `image_labels.lance` use the
single-commit stream-once Lance writer: batches are written to a temporary Arrow
stream and committed once at finalize time.

## Config

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

Recommended default:

```yaml
compact_tables: "text,image_labels"
```

## Archive

The previous experiment-heavy implementation was moved intact to:

`pipelines/wiki/old_pipelines/stage1_html_localize_image_ids_experimental_20260415`
