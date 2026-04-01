# 1_html_collect_image_urls_lance

Collect all `<img src=...>` URLs from raw HTML and record ordered
structured image entries into `text.info.html_images`.

Each item in `html_images` keeps the original HTML URL plus the local
match result:

- `image_url_raw`
- `image_url_normalized`
- `matched`
- `matched_image_id`
