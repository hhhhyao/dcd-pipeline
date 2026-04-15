# stage3_md_to_openai

Convert wiki markdown in `text.lance` into DCD-renderable OpenAI-style
conversation JSON.

The pipe rewrites only `text.lance`. It keeps `images.lance` and
`image_labels.lance` via symlink in local runs.

## Behavior

- strips only the leading YAML front matter block
- scans markdown left to right and emits ordered OpenAI `content` blocks
- keeps only local markdown images under `images/<id>` or `./images/<id>`
- ignores Markdown image alt text, including Stage2 `image_ref_id` alt text
- drops non-local markdown images entirely
- does not perform any image-size filtering

Each output row writes `data` as a top-level single-message array:

```json
[
  {
    "role": "user",
    "content": [
      { "type": "text", "text": "Paragraph before image.\n\n" },
      { "type": "image_url", "image_url": { "url": "images/part/hash/file.jpg" } },
      { "type": "text", "text": "\n\nParagraph after image." }
    ]
  }
]
```

## `info` updates

The pipe preserves existing metadata such as `url` and `title`, and updates:

```json
{
  "format": "openai",
  "image_ids": ["part/hash/file.jpg"],
  "dropped_nonlocal_images": 2
}
```

`image_ids` is rebuilt from the actual emitted `image_url` blocks in block
order.
Any upstream `image_refs` key is removed from `info`.

## Local Run

```bash
python3 pipelines/wiki/run_local/3_md_to_openai.py \
  workspace/md_lance/wiki_0320_en_has_pic_v2_md \
  workspace/openai_lance/wiki_0320_en_has_pic_v2_openai \
  --batch-size 128
```

## Tests

```bash
pytest -q pipelines/wiki/stage3_md_to_openai/tests/test_stage3_md_to_openai.py
```
