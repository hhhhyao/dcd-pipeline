# stage4_filter_images

Filter the OpenAI `image_url` blocks emitted by `stage3_md_to_openai` using
image label metadata supplied in the input batch.

The manifest declares JSON input/output for compatibility with the current
`dcd-cli` validator; the JSON payload itself is still the OpenAI-style
single-message array emitted by Stage3.

This stage does not tokenize, truncate, or split rows.

## Behavior

- reads `min_image_width` and `min_image_height` from config
- defaults to filtering images smaller than `28x28`
- reads image width and height from DCD multimodal batch input
  `image: [info]`
- expects the current DCD secondary-modality batch shape:
  one `image.id` / `image.info` list per text row, aligned through canonical
  `info.__defined__.links.images` or the legacy fallback `info.image_ids`
- keeps rows 1:1
- removes only `image_url` blocks whose known size is below the threshold
- keeps images when width/height metadata is missing from the batch
- rebuilds `info.__defined__.links.images` from the remaining emitted image
  blocks and removes legacy `info.image_ids`

## `info` updates

```json
{
  "format": "openai",
  "__defined__": {
    "links": {
      "images": [{ "id": "part/hash/keep.jpg" }]
    }
  },
  "filtered_small_images": 2
}
```

Zero-value counters are omitted.

## Tests

```bash
pytest -q pipelines/wiki/stage4_filter_images/tests/test_stage4_filter_images.py
```
