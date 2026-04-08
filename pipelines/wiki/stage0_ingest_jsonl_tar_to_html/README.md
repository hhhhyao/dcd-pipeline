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

Runtime config:

- `source_dir`: directory containing `part*.jsonl` and `part*.tar`
- `log_interval`: progress log interval in articles

Example:

```bash
python3 pipelines/wiki/run_local/0_ingest_jsonl_tar_to_html.py \
  workspace/source/wiki_0320_en_has_pic \
  workspace/html_lance/wiki_0320_en_has_pic_v2_raw
```
