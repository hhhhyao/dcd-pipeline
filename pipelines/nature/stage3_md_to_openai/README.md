# nature_stage3_md_to_openai

Convert Nature markdown rows into OpenAI-style multimodal message JSON.

The pipe scans markdown from left to right, emits text blocks and keeps only
local images under `images/<image_id>`. Non-local markdown images are dropped.

## Output Format

Each row stores one message array in `data`:

```json
[
  {
    "role": "user",
    "content": [
      {"type": "text", "text": "Text before image"},
      {"type": "image_url", "image_url": {"url": "images/<image_id>"}}
    ]
  }
]
```

`info.__defined__.links.images` is rebuilt from the emitted local image blocks.

## Local Run

```bash
python3 pipelines/nature/run_local/3_md_to_openai.py \
  /root/zhouyiren/data/interleaved/nature/md_lance/nature_test_v1_md \
  /root/zhouyiren/data/interleaved/nature/openai_lance/nature_test_v1_openai \
  --no-prepare
```
