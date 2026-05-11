# dclm_baseline_parquet_to_text_lance

Ingest pipe that converts DCLM baseline HuggingFace parquet shards into a DCD
`text.lance` dataset.

The pipe follows the generator-form ingest contract from current `dcd-cli`.
Bind the parquet root as a read-only volume named `source`.

Output columns:

- `id`: source `id`, or deterministic fallback `dclm-baseline-<sha1>`
- `data`: source `text`
- `info`: compact JSON with `source_file` plus all non-`text`/non-`id` columns
- `tags`: `dclm-baseline` plus `language` when present

Local example:

```bash
python3 pipelines/dclm_baseline/run_local/parquet_to_text_lance.py \
  --overwrite \
  --workers 4 \
  --max-rows 10000
```

