# fineweb_edu_parquet_to_text_lance

Ingest pipe that converts FineWeb-Edu HuggingFace parquet shards into a DCD
`text.lance` dataset.

The pipe follows the generator-form ingest contract from current `dcd-cli`.
Bind the parquet root as a read-only volume named `source`.

Output columns:

- `id`: source `id`, or deterministic fallback `fineweb-edu-<sha1>`
- `data`: source `text`
- `info`: compact JSON with `source_file` plus all non-`text`/non-`id` columns,
  including optional `date` when present
- `tags`: `fineweb-edu` plus `language` and `dump` when present

Local example:

```bash
python3 pipelines/fineweb_edu/run_local/parquet_to_text_lance.py \
  --overwrite \
  --workers 8 \
  --max-rows 10000
```

