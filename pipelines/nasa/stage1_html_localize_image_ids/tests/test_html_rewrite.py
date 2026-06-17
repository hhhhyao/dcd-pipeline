from __future__ import annotations

from workflow.html_rewrite import build_html_rewrite_plan, build_local_url_map
from plugins.wikimedia_production import (
    extract_img_urls_from_html,
    format_image_ref,
    normalize_image_url,
    rewrite_html,
)


def test_build_html_rewrite_plan_and_plugin_rewrite_use_image_ref_id() -> None:
    image_refs = {
        "img-1_refa": {
            "image_url_ori": "//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg",
        }
    }
    normalized_to_ref, _, _ = build_local_url_map(image_refs, normalize_image_url)
    html = (
        '<img src="//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg" '
        'srcset="abc 1x">'
        '<img src="https://example.com/missing.jpg">'
    )
    plan = build_html_rewrite_plan(
        html,
        extract_urls=extract_img_urls_from_html,
        normalize_url=normalize_image_url,
        format_image_ref=format_image_ref,
        normalized_to_ref=normalized_to_ref,
    )
    rewritten = rewrite_html(html, plan["replacements_by_raw_url"])
    assert 'src="images/img-1"' in rewritten
    assert '_image_ref_id="img-1_refa"' in rewritten
    assert "srcset=" not in rewritten
    assert plan["missing_urls"] == [{
        "image_url_raw": "https://example.com/missing.jpg",
        "image_url_normalized": "example.com/missing.jpg",
    }]
    assert plan["matched_normalized_urls"] == {"upload.wikimedia.org/wikipedia/commons/e/e2/Foo.jpg"}
    assert plan["used_image_ids"] == ["img-1"]
    assert plan["used_image_ref_ids"] == ["img-1_refa"]


def test_build_html_rewrite_plan_uses_only_image_url_ori() -> None:
    html = '<img src="https://example.com/a.jpg"><img src="https://example.com/b.jpg">'
    image_refs = {
        "img-a_ref": {
            "image_url_ori": "https://example.com/a.jpg",
            "image_url": "https://ignored.example/a.jpg",
        },
        "img-b_ref": {
            "image_url": "https://example.com/b.jpg",
        },
    }
    plan = build_html_rewrite_plan(
        html,
        extract_urls=lambda raw_html: [raw_html.split('"')[1]],
        normalize_url=lambda url: url,
        format_image_ref=format_image_ref,
        normalized_to_ref=build_local_url_map(image_refs, lambda url: url)[0],
    )
    rewritten = rewrite_html(html, plan["replacements_by_raw_url"])
    assert rewritten == '<img src="images/img-a" _image_ref_id="img-a_ref"><img src="https://example.com/b.jpg">'
    assert plan["missing_urls"] == []
    assert plan["used_image_ids"] == ["img-a"]
    assert plan["used_image_ref_ids"] == ["img-a_ref"]
