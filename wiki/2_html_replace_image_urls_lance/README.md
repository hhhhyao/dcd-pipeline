# 2_html_replace_image_urls_lance

Rewrite raw HTML `<img src=...>` URLs to local `images/<id>` using
`text.info.html_images` from the previous stage.

The stage builds a deterministic mapping:

- key: `html_images[*].image_url_raw`
- value: `html_images[*].matched_image_id`

Then each HTML `<img src>` is rewritten by key lookup instead of by positional
alignment with the Stage 1 list.

If the same raw URL appears multiple times in `html_images` with different
`matched_image_id` values, Stage 2 keeps the first one and emits an aggregated
warning, but it does not fail the batch.

After rewriting, Stage 2 removes `text.info.html_images` from downstream rows.
From this stage onward the HTML is considered localized, so downstream stages
should rely on:

- rewritten HTML `src="images/<id>"`
- `info.image_ids` rebuilt from the images actually rewritten in the HTML
