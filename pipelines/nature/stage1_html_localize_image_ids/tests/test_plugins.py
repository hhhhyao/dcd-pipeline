from __future__ import annotations

from plugins import nature_production
from plugins import wikimedia_production as plugin


def test_wikimedia_plugin_extract_and_normalize_and_format() -> None:
    html = (
        '<img src="//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg">'
        '<img alt="x" src="https://upload.wikimedia.org/wikipedia/commons/a/a5/%E5%9C%96.jpg">'
    )
    assert plugin.extract_img_urls_from_html(html) == [
        "//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/a/a5/%E5%9C%96.jpg",
    ]
    assert (
        plugin.normalize_image_url("//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg")
        == "upload.wikimedia.org/wikipedia/commons/e/e2/Foo.jpg"
    )
    assert (
        plugin.normalize_image_url("https://upload.wikimedia.org/wikipedia/commons/a/a5/%E5%9C%96.jpg")
        == "upload.wikimedia.org/wikipedia/commons/a/a5/圖.jpg"
    )
    assert plugin.format_image_ref("img-1", "img-1_hash") == {
        "src": "images/img-1",
        "image_ref_id": "img-1_hash",
    }


def test_wikimedia_plugin_rewrite_html_sets_src_and_image_ref_id() -> None:
    html = (
        '<img src="https://example.com/a.jpg" srcset="abc 1x">'
        '<img src="https://example.com/a.jpg">'
        '<img src="https://example.com/b.jpg"/>'
    )
    rewritten = plugin.rewrite_html(
        html,
        {
            "https://example.com/a.jpg": [
                {"src": "images/img-a", "image_ref_id": "img-a_ref"},
                None,
            ],
            "https://example.com/b.jpg": [
                {"src": "images/img-b", "image_ref_id": "img-b_ref"},
            ],
        },
    )
    assert rewritten == (
        '<img src="images/img-a" _image_ref_id="img-a_ref">'
        '<img src="https://example.com/a.jpg">'
        '<img src="images/img-b" _image_ref_id="img-b_ref"/>'
    )


def test_nature_plugin_normalizes_immersive_assets_and_rewrites_img() -> None:
    html = (
        '<picture><source srcset="./assets/foo/image-750.webp 750w, '
        './assets/foo/image-1500.webp 1500w">'
        '<img src="./assets/foo/image-750.jpg" data-srcset="./assets/foo/image-750.webp 750w">'
        "</picture>"
    )
    assert nature_production.extract_img_urls_from_html(html) == [
        "./assets/foo/image-750.jpg",
    ]
    assert (
        nature_production.normalize_image_url("./assets/foo/image-750.jpg")
        == "nature-asset/foo/image-750.jpg"
    )
    assert (
        nature_production.normalize_image_url(
            "https://www.nature.com/articles/assets/foo/image-750.jpg",
        )
        == "nature-asset/foo/image-750.jpg"
    )
    assert (
        nature_production.normalize_image_url(
            "https://www.nature.com/immersive/d41586-x/assets/foo/image-750.jpg",
        )
        == "nature-asset/foo/image-750.jpg"
    )

    rewritten = nature_production.rewrite_html(
        html,
        {
            "./assets/foo/image-750.jpg": [
                {"src": "images/img-1", "image_ref_id": "img-1_hash"},
            ],
        },
    )
    assert 'src="images/img-1"' in rewritten
    assert '_image_ref_id="img-1_hash"' in rewritten
    assert "data-srcset" not in rewritten
