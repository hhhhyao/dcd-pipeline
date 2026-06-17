# nasa_stage1_html_localize_image_ids

Rewrite NASA HTML image references from remote URLs to local
`images/<image_id>` references and deduplicate `image_labels.lance`.

## Input

An HTML Lance dataset containing:

- `text.lance`
- `images.lance`
- `image_labels.lance`

`text.info.image_refs` is the source of truth for matching HTML image URLs to
image IDs.

## Output

The pipe writes to `ctx.output_dir`:

- `text.lance`
- `images.lance` as a symlink to the input table
- `image_labels.lance`
- `image_url_missing.jsonl`
- `image_id_unmatched_warning.jsonl`
- `dataset.yaml`
- `run_info.yaml`

## NASA Matching

The default plugin is `plugins.nasa_production`. It normalizes common NASA
image forms including:

- `https://www.nasa.gov/wp-content/uploads/...`
- `https://images-assets.nasa.gov/...`
- `https://assets.science.nasa.gov/dynamicimage/assets/...`
- `images.nasa.gov/...`
- `./assets/...`

Matched `<img>` tags are rewritten with `src="images/<image_id>"` and an
`_image_ref_id` attribute for Stage2 markdown conversion.

## Local Run

```bash
python3 pipelines/nasa/run_local/1_html_localize_image_ids.py \
  /root/zhouyiren/data/interleaved/nasa/html_lance/nasa_test_v1 \
  /root/zhouyiren/data/interleaved/nasa/html_lance/nasa_test_v1_localized \
  --no-prepare
```
