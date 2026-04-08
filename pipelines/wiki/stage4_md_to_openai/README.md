# stage4_md_to_openai

Convert wiki markdown in `text.lance` into DCD-renderable OpenAI-style
conversation JSON.

The pipe rewrites only `text.lance`. It keeps `images.lance` and
`image_labels.lance` via symlink in local runs.

## Output Schema

Each output row writes `data` as a top-level message array:

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

Why this shape:

- DCD now recognizes OpenAI message JSON in
  `../../../../reference_repo/dcd/frontend/src/pages/viewers/TextDetailPage.tsx`
- DCD's multimodal OpenAI renderer accepts top-level message arrays and
  `{"messages":[...]}` objects; this pipe now emits the direct array form
- The renderer accepts `content` as a
  `list[dict]`
- Image parts must use `{"type":"image_url","image_url":{"url":"images/..."}}`
  so `../../../../reference_repo/dcd/frontend/src/mediaUrls.ts` can rewrite them to the
  dataset image API

## Processing Flow

The implementation is in [__init__.py](./__init__.py).

### 1. `map()`

[`map()`](./__init__.py) is the batch entrypoint.

It:

- reads `max_small_area` and `message_role` from `ctx.config`
- resolves `image_labels.lance` primarily from
  `/datasets/<ctx.dataset>/image_labels.lance`
- caches label sizes per dataset in-process
- falls back to local-run paths only when `/datasets/<ctx.dataset>` is not
  available
- converts markdown to ordered content parts with
  `_md_to_openai_content_parts()`
- wraps the content into a top-level message array
- rewrites `info.format` to `"openai"`

### 2. `_strip_front_matter()`

[`_strip_front_matter()`](./__init__.py) removes only the leading YAML front
matter block:

```md
---
title: ...
url: ...
---
```

It does not remove later `---` separators inside the body.

### 3. `_md_to_openai_content_parts()`

[`_md_to_openai_content_parts()`](./__init__.py) scans markdown left to right
and emits ordered OpenAI content parts.

Supported markdown image forms:

```md
![alt](images/part/hash/file.jpg)
[![alt](images/part/hash/file.jpg)](https://example.com/page)
```

These become `image_url` parts.

Non-local image URLs are dropped entirely:

```md
![x](https://example.com/a.jpg)
![x](//upload.wikimedia.org/a.png)
[![x](https://example.com/a.jpg)](https://example.com/page)
```

### 4. `_parse_local_image_id()`

[`_parse_local_image_id()`](./__init__.py) keeps only local image paths under
`images/<id>` or `./images/<id>`, strips query / fragment suffixes, and keeps
the full nested path.

Example:

```text
./images/part2026-03-20-00000/hash/file.jpg?width=100#frag
```

becomes:

```text
part2026-03-20-00000/hash/file.jpg
```

### 5. Small-image filtering

Small-image filtering is handled by [`_image_area()`](./__init__.py) and
[`_append_local_image_part()`](./__init__.py).

Important change:

- filtering uses only `image_labels.lance` `info.width` / `info.height`
- it does **not** open image bytes
- if width/height metadata is missing, the image is kept

This matches the current requirement to avoid probing image content.

## `info` Updates

The pipe preserves existing metadata such as `url`, `title`, and `image_ids`.

It updates:

```json
{
  "format": "openai",
  "filtered_small_images": 1,
  "dropped_nonlocal_images": 2
}
```

Zero-value counters are omitted.

## Local Run

```bash
python3 pipelines/wiki/run_local/4_md_to_openai.py \
  workspace/md_lance/wiki_0320_en_has_pic_v2_md \
  workspace/openai_lance/wiki_0320_en_has_pic_v2_openai \
  --batch-size 128
```

The local runner script will:

- rewrite `text.lance`
- symlink `images.lance`
- symlink `image_labels.lance`
- run `prepare_dataset` by default

## Quick Validation

```bash
python3 - <<'PY'
import json
import lance

row = lance.dataset(
    "workspace/openai_lance/wiki_0320_en_has_pic_v2_openai/text.lance"
).to_table(limit=1).to_pylist()[0]

payload = json.loads(row["data"])
info = json.loads(row["info"])

print(info["format"])
print(payload[0]["role"])
print(payload[0]["content"][:3])
PY
```

Expected:

- `info.format == "openai"`
- `payload[0].role == "user"` unless overridden by config
- image parts use `image_url.url = "images/..."`
- front matter is gone from the first text part

## Tests

```bash
pytest -q pipelines/wiki/stage4_md_to_openai/tests/test_stage4_md_to_openai.py
```
