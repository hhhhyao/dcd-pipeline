# wiki

Wiki data conversion and pipe workflows.

## Structure

- `0_ingest_jsonl_tar_to_html_lance/`: Stage-0 ingest pipe for raw source -> HTML Lance.
- `run_pipeline.sh`: Entrypoint for the raw-to-HTML conversion.
- `1_html_collect_image_urls_lance/` to `4_md_to_openai_lance/`: Ordered follow-up stages.

## Typical flow

1. Run `wiki/0_ingest_jsonl_tar_to_html_lance/run_local.py` to build raw HTML Lance.
2. Run `wiki/1_html_collect_image_urls_lance/run_local.py`.
3. Run `wiki/2_html_replace_image_urls_lance/run_local.py`.
4. Run `wiki/3_parse_html/run_local.py` to build Markdown Lance.
5. Run `wiki/4_md_to_openai_lance/run_local.py` to build OpenAI Lance.
