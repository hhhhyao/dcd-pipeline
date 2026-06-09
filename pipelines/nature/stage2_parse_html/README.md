# nature_stage2_parse_html

Convert localized Nature HTML into cleaned markdown or simplified HTML.

This pipe reuses the HTML extraction and markdown conversion logic from the
wiki stage2 pipe. Stage1-localized image tags are converted to local markdown
images such as:

```markdown
![<image_ref_id>](images/<image_id>)
```

## Input

`text.lance` columns:

- `id`
- `data` containing HTML
- `info` JSON metadata

## Output

`text.lance` with unchanged `id`, transformed `data`, and updated
`info.format`.

## Local Run

```bash
python3 pipelines/nature/run_local/2_parse_html.py \
  /root/zhouyiren/data/interleaved/nature/html_lance/nature_test_v1_localized \
  /root/zhouyiren/data/interleaved/nature/md_lance/nature_test_v1_md \
  --no-prepare
```
