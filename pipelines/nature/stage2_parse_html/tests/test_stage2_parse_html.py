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


def test_map_converts_nature_html_to_markdown() -> None:
    html = (
        "<html><head><title>Nature Example</title></head><body>"
        "<article><h1>Heading</h1><p>Paragraph text.</p></article>"
        "</body></html>"
    )
    batch = {
        "id": ["row-1"],
        "data": [html],
        "info": [json.dumps({"url": "https://www.nature.com/articles/example"})],
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
        "info": [json.dumps({"url": "https://www.nature.com/articles/example"})],
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
