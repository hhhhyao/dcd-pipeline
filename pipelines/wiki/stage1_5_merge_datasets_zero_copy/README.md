# stage1_5_merge_datasets_zero_copy

Local ingest pipe that merges multiple Stage1 wiki datasets.

It concatenates `text.lance`, deduplicates `image_labels.lance` by first-seen
image id, and creates a new `images.lance` by committing Lance manifest metadata
that references each source dataset's existing `images.lance/data/*.lance` files.
It does not materialize image bytes into the output dataset.

All input `images.lance` tables must have the same schema and use
`image_bytes: large_binary`. Source datasets must remain available and immutable
while the merged dataset is used.

## Config

- `dataset_paths`: JSON list of local dataset root paths.
- `output_name`: optional metadata name.
- `batch_size`: Lance scan batch size.
- `progress_every`: progress logging interval.
- `compact_tables`: defaults to `image_labels`; `images` is ignored to preserve
  zero-copy storage.
- `allow_text_id_duplicates`: default `true`.
- `overwrite`: default `true`.
