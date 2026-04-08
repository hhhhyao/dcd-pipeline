# stage1_html_localize_image_ids

Active wiki stage that localizes HTML image references using the image IDs
already present in each row.

Input is the Stage-0 HTML Lance dataset. The pipe only uses image IDs
that already exist in each row's `text.info.image_ids`:

1. Load `image_labels.lance`
2. Resolve candidate original URLs for those existing image IDs
3. Rewrite matching HTML `<img src=...>` to `images/<id>`
4. Rebuild `text.info.image_ids` from the images actually rewritten

This pipe intentionally does not:

- collect global HTML image candidates
- match images outside the current row's existing `image_ids`
- supplement missing image IDs

The output contract is:

- localized HTML in `text.data`
- `text.info.image_ids` rebuilt from successfully rewritten images
- no `text.info.html_images`
