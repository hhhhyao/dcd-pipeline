from __future__ import annotations

import json
from types import SimpleNamespace

from lxml.html import document_fromstring

import stage2_parse_html as pipe


def _ctx(config: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        config=config or {},
        set_progress=lambda *args, **kwargs: None,
        report_error=lambda *args, **kwargs: None,
    )


def test_map_converts_nasa_html_to_markdown() -> None:
    html = (
        "<html><head><title>NASA Example</title></head><body>"
        "<article><h1>Heading</h1><p>Paragraph text.</p></article>"
        "</body></html>"
    )
    batch = {
        "id": ["row-1"],
        "data": [html],
        "info": [json.dumps({"url": "https://www.nasa.gov/news-release/example/"})],
    }

    out = pipe.map(batch, _ctx({"remove_ref": False, "out_format": "md", "timeout": 30}))

    assert out["id"] == ["row-1"]
    assert "Heading" in out["data"][0]
    assert "Paragraph text." in out["data"][0]
    assert json.loads(out["info"][0])["format"] == "md"


def test_local_image_ref_becomes_markdown_alt_text() -> None:
    html = (
        "<html><body><article>"
        '<img src="images/img-1" _image_ref_id="img-1_ref">'
        "</article></body></html>"
    )
    batch = {
        "id": ["row-1"],
        "data": [html],
        "info": [json.dumps({"url": "https://www.nasa.gov/news-release/example/"})],
    }
    result = pipe.map(batch, _ctx({"remove_ref": False, "out_format": "md"}))

    assert "![img-1_ref](images/img-1)" in result["data"][0]


def test_extract_image_captions_from_figure() -> None:
    html = (
        "<html><body><figure>"
        '<img src="images/img-1" alt="A figure">'
        "<figcaption>Figure caption text</figcaption>"
        "</figure></body></html>"
    )
    tree = document_fromstring(html)

    assert pipe.extract_image_captions(tree) == [
        {
            "url": "images/img-1",
            "alt": "A figure",
            "caption": "Figure caption text",
        },
    ]


def test_nasa_wordpress_content_and_json_ld_meta() -> None:
    json_ld = {
        "@graph": [
            {
                "@type": "WebPage",
                "@id": "https://www.nasa.gov/image-article/apollo-17-blue-marble/#webpage",
                "url": "https://www.nasa.gov/image-article/apollo-17-blue-marble/",
                "name": "NASA page title",
            },
            {
                "@type": "NewsArticle",
                "headline": "Apollo 17 Blue Marble",
                "datePublished": "2024-01-01T12:00:00+00:00",
                "author": {"@type": "Person", "name": "NASA"},
                "description": "Earth as seen by Apollo 17.",
            },
        ],
    }
    html = (
        "<html><head>"
        f"<script type=\"application/ld+json\">{json.dumps(json_ld)}</script>"
        "</head><body><main id=\"primary\"><article>"
        "<div class=\"usa-article-content\"><div class=\"entry-content\">"
        "<h1>Apollo image</h1><p>Mission text.</p>"
        "</div>"
        "<form class=\"hds-single-form-embed\">Was this page helpful?</form>"
        "<div class=\"related-posts\">Related stories</div>"
        "</div></article></main></body></html>"
    )

    result = pipe.run_extract_pipeline(
        html,
        "https://www.nasa.gov/image-article/apollo-17-blue-marble/",
        remove_ref=False,
    )

    assert "Mission text." in result.markdown
    assert "Was this page helpful" not in result.markdown
    assert "Related stories" not in result.markdown
    assert result.meta["title"] == "Apollo 17 Blue Marble"
    assert result.meta["author"] == "NASA"
    assert result.meta["date"] == "2024-01-01T12:00:00+00:00"
