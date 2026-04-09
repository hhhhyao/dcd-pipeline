# stage4_filter_images

Filter the OpenAI `image_url` blocks emitted by `stage3_md_to_openai` using
`image_labels` metadata supplied in the input batch.

This stage does not tokenize, truncate, or split rows.

## Behavior

- reads `min_image_width` and `min_image_height` from config
- reads image width and height from multimodal batch input
  `image_labels: [id, info]`
- keeps rows 1:1
- removes only `image_url` blocks whose known size is below the threshold
- keeps images when width/height metadata is missing from the batch
- rebuilds `info.image_ids` from the remaining emitted image blocks

## `info` updates

```json
{
  "format": "openai",
  "image_ids": ["part/hash/keep.jpg"],
  "filtered_small_images": 2
}
```

Zero-value counters are omitted.

## Tests

```bash
pytest -q pipelines/wiki/stage4_filter_images/tests/test_stage4_filter_images.py
```
