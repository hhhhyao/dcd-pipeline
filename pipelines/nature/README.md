# Nature Pipeline

This directory contains DCD pipes and local helpers for processing Nature
article HTML and images into multimodal datasets.

## Stages

- `stage0_ingest_jsonl_tar_to_html`: ingest `part*.jsonl` + `part*.tar`
  raw data into HTML Lance tables.
- `stage1_html_localize_image_ids`: rewrite Nature HTML image references to
  local `images/<id>` references and deduplicate image labels.
- `stage2_parse_html`: convert localized HTML to markdown.
- `stage3_md_to_openai`: convert markdown into OpenAI-style multimodal JSON.
- `stage4_filter_images`: filter OpenAI image blocks by image label size.

Local execution helpers live in `run_local/`.

## Preprocess Helpers

- `preprocess0-0_html_crawl_test_nature.py`: collect candidate Nature URLs.
- `preprocess0-1_nature_oa_filter.py`: annotate raw `part*.jsonl` rows with
  an `open_access` boolean and URL pattern fields.
- `preprocess0-2_img_url_crawl_test_nature.py`: collect page image URLs.
- `preprocess0-3_map_html_and_img_test_nature.py`: build raw `part*.jsonl`
  and `part*.tar` files from page/image mappings.

## Default Local Data Flow

```text
/root/zhouyiren/data/interleaved/nature/raw_data
  -> /root/zhouyiren/data/interleaved/nature/html_lance/nature_test_v1
  -> /root/zhouyiren/data/interleaved/nature/html_lance/nature_test_v1_localized
  -> /root/zhouyiren/data/interleaved/nature/md_lance/nature_test_v1_md
  -> /root/zhouyiren/data/interleaved/nature/openai_lance/nature_test_v1_openai
  -> /root/zhouyiren/data/interleaved/nature/openai_lance/nature_test_v1_openai_filtered
```

Run from the repository root with the `dcd` conda environment when Lance and
pipe dependencies are needed.
