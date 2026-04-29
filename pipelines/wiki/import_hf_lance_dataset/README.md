# stage0_5_import_hf_lance_dataset

Generic HF import pipe for wiki text+image Lance datasets.

It downloads a Hugging Face dataset repository, reads `text.lance`,
`images.lance`, and `image_labels.lance`, then yields generator-form DCD
batches so the runner writes a managed dataset.

## Pairing Modes

- `row_order`: pair `images.lance` and `image_labels.lance` by row position.
  Use this for raw Stage0 snapshots when you want to preserve the original
  row-aligned layout.
- `id_join`: drive output from `image_labels.lance` and look up image bytes by
  `id` in `images.lance`. Use this for Stage1+ datasets where labels may be
  deduplicated and the two tables may no longer have matching row counts.

The pipe does not import sidecar files such as `run_info.yaml` or
`image_url_missing.jsonl`; it only imports canonical Lance rows.

Private Hugging Face repos should use a DCD user secret named `HF_TOKEN`.

## Dependencies

The Lance Python API is provided by the `pylance` package and imported as
`lance`. Do not replace it with the unrelated `lance` package.
