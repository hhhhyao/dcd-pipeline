# Nature Process Parse Table

`process_parse_table` is a DCD-compatible map pipe that converts HTML table
pages into GitHub-flavored Markdown table text.

The pipe reads HTML from `text.data` and writes Markdown to `text.data`.  It
also accepts a raw JSONL-style `html` column when used in local tests or
ad-hoc scripts.  Table metadata such as `html_title`, `table_number`, and
`table_url` is preserved in `text.info` when present.

## Input

```yaml
text: [id, data, info, tags]
```

`data` should contain either a full HTML document with table elements or a
standalone `<table>...</table>` fragment.

The sample source used while building this pipe is:

```text
/root/zhouyiren/data/interleaved/nature/web_eng_20260608_sample/part2026-06-08-00000_OA/part2026-06-08-00000_table.jsonl
```

## Output

```yaml
text: [id, data, info, tags]
```

`data` contains Markdown table text.  `info` is updated with:

- `format: "md"`
- `table_parse_status`: `ok`, `no_table`, or `error`
- `table_count`
- `tables_converted`
- `table_row_counts`
- `table_column_counts`
- `table_title` when it can be found

## Config

- `table_index`: 0-based table index to convert.  `-1` converts all top-level
  tables.  Default: `-1`.
- `include_title`: prefix output with the table title.  Default: `false`.
- `title_heading_level`: heading level used when `include_title` is enabled.
  Default: `3`.
- `span_fill`: how to fill cells expanded from `rowspan` or `colspan`.
  `repeat` keeps context in every expanded cell; `blank` keeps a visual
  approximation of the span.  Default: `repeat`.
- `collapse_headers`: collapse multiple HTML header rows into one Markdown
  header row.  Default: `true`.
