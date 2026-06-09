# nature_stage4_filter_images

Filter OpenAI image blocks using image label width and height metadata.

The pipe keeps rows 1:1 and removes only `image_url` blocks whose known size is
smaller than the configured thresholds. Images without known dimensions, such
as some SVGs, are kept.

## Config

- `min_image_width`, default `28`
- `min_image_height`, default `28`

## Local Run

```bash
python3 pipelines/nature/run_local/4_filter_images.py \
  /root/zhouyiren/data/interleaved/nature/openai_lance/nature_test_v1_openai \
  /root/zhouyiren/data/interleaved/nature/openai_lance/nature_test_v1_openai_filtered \
  --no-prepare
```
