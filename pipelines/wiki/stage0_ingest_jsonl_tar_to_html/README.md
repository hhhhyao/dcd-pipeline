# stage0_ingest_jsonl_tar_to_html

Stage 0 is now organized as a standard DCD ingest pipe:

- `manifest.yaml`
- `main.py`
- `__init__.py`
- `requirements.txt`
- `README.md`

Local-only runner scripts live under `../run_local/` so the uploaded pipe
package stays minimal and closer to the platform layout.

The pipe entrypoint is `ingest(ctx)`, and it writes:
- `text.lance`
- `images.lance`
- `image_labels.lance`

This pipe currently remains a legacy ingest pipe. Its manifest omits
`output_fields` on purpose so newer `dcd-cli` / `dcd-server` releases
keep routing it through the `ctx.output_dir` code path instead of the
new generator-form ingest path.

Current Stage-0 behavior mirrors the raw-dump reference ingest:

- article IDs are `sha256(html)`
- image IDs are `sha256(image_bytes)`
- `images.lance.image_bytes` is `large_binary`
- HTML stays in raw remote-URL form for the next rewrite stage
- duplicate image/image_label rows are preserved here and deduplicated in Stage 1
- Lance writes default to `stream_once`, which buffers part outputs through
  Arrow streams and commits each table once
- `text.info.__defined__.links.images` lists image ids only for refs with
  `image_url_ori`
- `text.info.image_refs` stores article-local image metadata keyed by
  `<image_id>_<sha256(image_url_ori)>`
- `image_labels.info` keeps only image-stable metadata such as `image_md5`,
  `width`, `height`, `channel`, and `size_bytes`, plus
  `__defined__.links.text` back to the source text row
- caption/url/file fields are kept out of `image_labels.info` because they can
  vary across articles for the same image bytes

Runtime config:

- `source_dir`: directory containing `part*.jsonl` and `part*.tar`
- `log_interval`: progress log interval in articles
- `write_strategy`: `stream_once` or `append_parts`

Example:

```bash
python3 pipelines/wiki/run_local/0_ingest_jsonl_tar_to_html.py \
  workspace/source/wiki_0320_en_has_pic \
  workspace/html_lance/wiki_0320_en_has_pic_v2_raw
```
