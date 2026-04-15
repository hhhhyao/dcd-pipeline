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
   - For Stage1-localized images, maps `_image_ref_id` into the Markdown
     image alt text, so output uses `![<image_ref_id>](images/<image_id>)`
   - Converts the cleaned content to markdown and simplified HTML
3. Writes the selected format back into `data`.

Items with empty or missing `data` are passed through unchanged.

## Testing

From the repo root:

```
dcd pipe test pipe-demos/parse_html
```

### Test layout

| File | What it covers |
|------|----------------|
| `test_parse_html.py` | Pipe `map()` function, snapshot regression against `examples/`, and fixture cases from `tests/fixtures/` |
| `test_extraction.py` | Snapshot regression for the HTML-to-markdown and HTML-to-simple-HTML converters |
| `test_media.py` | Audio and video element handling (cleaner + both converters) |
| `test_wiki_converter.py` | Wiki infobox cleanup, image alt-text, table post-processing, whitespace normalisation |
| `test_wiki_cleaner.py` | Wiki cleaning passes (magnify links, presentation tables, reference sections, noprint, etc.) |
| `test_nested_tables.py` | Nested-table flattening |
| `test_math.py` | LaTeX / math element extraction and conversion |
| `test_code.py` | Code block normalisation (Sphinx highlight divs, inline code) |

### Adding a fixture case

Create a directory under `tests/fixtures/<case_name>/` with:

```
<case_name>/
  input.json       # {"id": "...", "info": "{\"url\": \"...\"}"}
  input.html        # raw HTML source
  expected.json     # {"id": "...", "info": "..."}
  expected.md       # expected markdown output
```

Any test using the `html_fixture_case` parameter picks up the new case automatically.
