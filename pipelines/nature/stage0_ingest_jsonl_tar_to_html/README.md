# nature_stage0_ingest_jsonl_tar_to_html

Ingest Nature `part*.jsonl` + `part*.tar` raw data into an HTML Lance
dataset.

## Input

For local runs, `source_dir` must contain matched raw-data pairs:

```text
part*.jsonl
part*.tar
```

For server-side DCD jobs, pin a Raw input under slot `source`. The pipe
materializes that raw input into a temporary directory and then processes the
same `part*.jsonl` + `part*.tar` layout.

Each JSONL row is one article with raw `html` and `images[*].image_file`
entries that point into the corresponding tar.

## Output

The pipe writes to `ctx.output_dir`:

- `text.lance`
- `images.lance`
- `image_labels.lance`

The table schema follows the wiki stage0 pipe. Nature-specific image metadata
such as `content_type`, `download_bytes`, `image_sha256`, `source`, and
`resolved_image_url` is preserved in text-side image refs or image label info.

## Nature Differences

- Raster images are read with Pillow.
- SVG bytes are preserved and width/height are parsed from `width`, `height`,
  or `viewBox` when available.
- Image IDs are `sha256(image_bytes)`.
- Text IDs are `sha256(html)`.

## Local Run

```bash
python3 pipelines/nature/run_local/0_ingest_jsonl_tar_to_html.py \
  /root/zhouyiren/data/interleaved/nature/raw_data \
  /root/zhouyiren/data/interleaved/nature/html_lance/nature_test_v1
```
