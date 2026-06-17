# NASA Local Runners

Local helpers for running the NASA pipeline stages against filesystem Lance
datasets.

Run from the repository root with the `dcd` conda environment:

```bash
conda activate dcd
```

Default flow:

```bash
python3 pipelines/nasa/run_local/0_ingest_jsonl_tar_to_html.py
python3 pipelines/nasa/run_local/1_html_localize_image_ids.py --no-prepare
python3 pipelines/nasa/run_local/2_parse_html.py --no-prepare
python3 pipelines/nasa/run_local/3_md_to_openai.py --no-prepare
python3 pipelines/nasa/run_local/4_filter_images.py --no-prepare
```
