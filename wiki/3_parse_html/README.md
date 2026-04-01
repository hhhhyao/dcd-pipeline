# parse_html_repo

A transform pipe that converts raw HTML into cleaned markdown or
simplified HTML using the extract pipeline.

## Input (`text.lance` columns)

| Field  | Type   | Description                                  |
|--------|--------|----------------------------------------------|
| `id`   | string | Item identifier                              |
| `data` | string | Raw HTML source                              |
| `info` | string | JSON metadata; `url` is read if present      |

## Output

| Field  | Type   | Description                              |
|--------|--------|------------------------------------------|
| `id`   | string | Unchanged                                |
| `data` | string | Cleaned markdown (default) or simple HTML |

## Config

| Key          | Type   | Default | Description                                      |
|--------------|--------|---------|--------------------------------------------------|
| `remove_ref` | bool   | false   | Strip reference-style links from the output       |
| `out_format` | string | `"md"`  | Output format: `"md"` for markdown, `"html"` for simplified HTML |

## How it works

1. Reads the raw HTML from `data` and optionally `url` from `info` JSON.
2. Calls `run_extract_pipeline(source_html, url, remove_ref=...)` which:
   - Parses the HTML into an lxml tree
   - Extracts page metadata (title, author, date, etc.)
   - Cleans the tree (removes ads, nav, scripts, boilerplate)
   - Converts the cleaned content to markdown and simplified HTML
3. Writes the selected format back into `data`.

Items with empty or missing `data` are passed through unchanged.
