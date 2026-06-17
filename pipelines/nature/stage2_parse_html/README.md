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

When `info.tables` is present, it should contain the fetched Nature
`/tables/<n>` pages for the article. Stage2 extracts the first HTML `<table>`
from each record and injects it into the matching in-article table placeholder
before converting to Markdown.

## Output

`text.lance` with unchanged `id`, transformed `data`, and updated
`info.format`.

For rows with table records, raw `info.tables` is removed after conversion and
replaced with:

- `table_count`: number of table records seen
- `tables_injected`: number of tables inserted into the article content

## Local Run

```bash
python3 pipelines/nature/run_local/2_parse_html.py \
  /root/zhouyiren/data/interleaved/nature/html_lance/nature_test_v1_localized \
  /root/zhouyiren/data/interleaved/nature/md_lance/nature_test_v1_md \
  --no-prepare
```
