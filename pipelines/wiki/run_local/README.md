# run_local

This directory contains local execution helpers for the active wiki pipeline.

Active scripts:

- `0_ingest_jsonl_tar_to_html.py`
- `1_html_localize_image_ids.py`
- `3_parse_html.py`
- `4_md_to_openai.py`

Deprecated local scripts should not be added back here once a stage has been moved to `old_pipelines/`.
