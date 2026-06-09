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
