from __future__ import annotations

from workflow.html_rewrite import build_html_rewrite_plan, build_local_url_map
from plugins.wikimedia_production import (
    extract_img_urls_from_html,
    format_image_ref,
    normalize_image_url,
    rewrite_html,
)


def test_build_html_rewrite_plan_and_plugin_rewrite_removes_srcset_and_tracks_missing() -> None:
    label_infos = {
        "img-1": [
            {
                "image_url_ori": "//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg",
                "image_url": "https://upload.wikimedia.org/wikipedia/commons/e/e2/Foo.jpg",
            }
        ]
    }
    normalized_to_image_id, _, _ = build_local_url_map(["img-1"], label_infos, normalize_image_url)
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
        normalized_to_image_id=normalized_to_image_id,
    )
    rewritten = rewrite_html(html, plan["replacements_by_raw_url"])
    assert 'src="images/img-1"' in rewritten
    assert "srcset=" not in rewritten
    assert plan["missing_urls"] == [{
        "image_url_raw": "https://example.com/missing.jpg",
        "image_url_normalized": "example.com/missing.jpg",
    }]
    assert plan["matched_normalized_urls"] == {"upload.wikimedia.org/wikipedia/commons/e/e2/Foo.jpg"}
    assert plan["used_image_ids"] == ["img-1"]


def test_build_html_rewrite_plan_only_uses_extractor_urls() -> None:
    def extract_only_first(_html: str) -> list[str]:
        return ["https://example.com/a.jpg"]

    html = '<img src="https://example.com/a.jpg"><img src="https://example.com/b.jpg">'
    plan = build_html_rewrite_plan(
        html,
        extract_urls=extract_only_first,
        normalize_url=lambda url: url,
        format_image_ref=lambda image_id: f"images/{image_id}",
        normalized_to_image_id={"https://example.com/a.jpg": "img-a", "https://example.com/b.jpg": "img-b"},
    )
    rewritten = rewrite_html(html, plan["replacements_by_raw_url"])
    assert rewritten == '<img src="images/img-a"><img src="https://example.com/b.jpg">'
    assert plan["missing_urls"] == []
    assert plan["matched_normalized_urls"] == {"https://example.com/a.jpg"}
    assert plan["used_image_ids"] == ["img-a"]
