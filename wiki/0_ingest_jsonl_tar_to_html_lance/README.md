# 0_ingest_jsonl_tar_to_html_lance

Stage 0 is now organized as a standard DCD ingest pipe:

- `manifest.yaml`
- `main.py`
- `__init__.py`
- `requirements.txt`
- `README.md`
- `run_local.py`

The pipe entrypoint is `ingest(ctx)`, and it writes:
- `text.lance`
- `images.lance`
- `image_labels.lance`

Runtime config:

- `source_dir`: directory containing `part*.jsonl` and `part*.tar`
- `log_interval`: progress log interval in articles

Example:

```bash
python3 wiki/0_ingest_jsonl_tar_to_html_lance/run_local.py \
  workspace/source/wiki_0320_en_has_pic \
  workspace/html_lance/wiki_0320_en_has_pic_v2_raw
```
