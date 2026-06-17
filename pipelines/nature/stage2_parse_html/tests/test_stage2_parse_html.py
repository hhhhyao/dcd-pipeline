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


def test_table_records_are_injected_into_markdown() -> None:
    html = (
        "<html><head><title>Nature Example</title></head><body><article>"
        "<h1>Heading</h1><p>Before table.</p>"
        '<div class="c-article-table" data-test="inline-table" id="table-1">'
        "<figure>"
        '<figcaption><b id="Tab1">Table 1 Features and their count.</b></figcaption>'
        '<div class="u-text-right u-hide-print">'
        '<a href="/articles/example/tables/1">Full size table</a>'
        "</div>"
        "</figure>"
        "</div>"
        "<p>After table.</p>"
        "</article></body></html>"
    )
    table_html = (
        "<html><body>"
        '<h1 id="table-1-title">Table 1 Features and their count.</h1>'
        '<div class="c-article-table-container">'
        "<table>"
        "<thead><tr><th><p>Molecular</p></th><th><p>Biochemical</p></th></tr></thead>"
        "<tbody><tr><td><p>1. DCN</p></td><td><p>1. LVEDP</p></td></tr></tbody>"
        "</table>"
        "</div>"
        "</body></html>"
    )
    batch = {
        "id": ["row-1"],
        "data": [html],
        "info": [
            json.dumps({
                "url": "https://www.nature.com/articles/example",
                "tables": [
                    {
                        "table_number": 1,
                        "table_url": "https://www.nature.com/articles/example/tables/1",
                        "html": table_html,
                        "html_title": "Table 1 Features and their count. | Scientific Reports",
                    },
                ],
            }),
        ],
    }

    result = pipe.map(batch, _ctx({"remove_ref": False, "out_format": "md"}))
    markdown = result["data"][0]
    info = json.loads(result["info"][0])

    assert "Full size table" not in markdown
    assert "Table 1 Features and their count." in markdown
    assert "| Molecular | Biochemical |" in markdown
    assert "| 1. DCN | 1. LVEDP |" in markdown
    assert info["table_count"] == 1
    assert info["tables_injected"] == 1
    assert "tables" not in info


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


def test_postprocess_nature_markdown_removes_article_chrome() -> None:
    markdown = """---
title: Example Article
---

Download PDF

- Article
- Open access
- Published: 09 December 2020

# Example article title

- First Author1,
- Second Author2 &
- Third Author3Show authors

*Nature Communications* **volume 11**, Article number: 6314 (2020)
 Cite this article

- 10k Accesses

- 21 Citations

- 39 Altmetric

- Metrics details

### Subjects

- Biology
- Cell biology

## Abstract

Abstract text.

### Similar content being viewed by others

![](https://example.com/thumb.png)

### Recommended article

Article Open access 04 October 2024

## Introduction

Intro text.

***Fig. 1: A useful figure.***
![figure 1](images/img-1)

Full size image

Caption text.

## References

1. Reference that should be removed.
"""

    out = pipe.postprocess_nature_markdown(markdown, remove_ref=True)

    assert "Download PDF" not in out
    assert "First Author" not in out
    assert "Article number" not in out
    assert "Accesses" not in out
    assert "Altmetric" not in out
    assert "Subjects" not in out
    assert "Similar content being viewed by others" not in out
    assert "Recommended article" not in out
    assert "Full size image" not in out
    assert "References" not in out
    assert "# Example article title" in out
    assert "## Abstract" in out
    assert "Abstract text." in out
    assert "## Introduction" in out
    assert "Intro text." in out
    assert "![figure 1](images/img-1)" in out
    assert "Caption text." in out


def test_postprocess_removes_download_pdf_lines() -> None:
    markdown = """# Example article title

Download PDF

Paragraph before link form.

[Download PDF](https://www.nature.com/articles/example.pdf)

Paragraph after link form.
"""

    out = pipe.postprocess_nature_markdown(markdown, remove_ref=False)

    assert "Download PDF" not in out
    assert "Paragraph before link form." in out
    assert "Paragraph after link form." in out


def test_postprocess_removes_full_size_image_prompts() -> None:
    markdown = """# Example article title

***Fig. 1: A useful figure.***
![figure 1](images/img-1)

Full size image

Caption text.

![figure 2](images/img-2)
[Full size image](https://media.springernature.com/full/example.png)
Second caption text.
"""

    out = pipe.postprocess_nature_markdown(markdown, remove_ref=False)

    assert "Full size image" not in out
    assert "![figure 1](images/img-1)" in out
    assert "Caption text." in out
    assert "![figure 2](images/img-2)" in out
    assert "Second caption text." in out


def test_postprocess_removes_similar_content_recommendation_block() -> None:
    markdown = """# Example article title

## Results

Main article text before recommendation.

### Similar content being viewed by others

![thumbnail](https://example.com/thumb.png)

### Recommended article

Article Open access 04 October 2024

### Another recommended article

Article Open access 05 October 2024

## Discussion

Main article text after recommendation.
"""

    out = pipe.postprocess_nature_markdown(markdown, remove_ref=False)

    assert "Similar content being viewed by others" not in out
    assert "Recommended article" not in out
    assert "Article Open access 04 October 2024" not in out
    assert "Article Open access 05 October 2024" not in out
    assert "Main article text before recommendation." in out
    assert "## Discussion" in out
    assert "Main article text after recommendation." in out


def test_postprocess_removes_post_title_authors_metrics_and_subjects() -> None:
    markdown = """---
title: Example Article
---

- Article
- Open access
- Published: 09 December 2020

# Example article title

- First Author1,
- Second Author2 &
- Third Author3Show authors

*Scientific Reports* **volume 15**, Article number: 41542 (2025)
Cite this article

- 728 Accesses
- 13 Altmetric
- Metrics details

### Subjects

- Biomarkers
- Computational biology

## Abstract

Abstract text starts here.
"""

    out = pipe.postprocess_nature_markdown(markdown, remove_ref=False)

    assert "- Article" in out
    assert "- Open access" in out
    assert "- Published: 09 December 2020" in out
    assert "# Example article title" in out
    assert "First Author" not in out
    assert "Show authors" not in out
    assert "Article number" not in out
    assert "Cite this article" not in out
    assert "Accesses" not in out
    assert "Altmetric" not in out
    assert "Metrics details" not in out
    assert "Subjects" not in out
    assert "Biomarkers" not in out
    assert "## Abstract" in out
    assert "Abstract text starts here." in out


def test_postprocess_removes_references_tail_when_configured() -> None:
    markdown = """# Example article title

## Discussion

Main article conclusion.

## References

1. Reference that should be removed.

## Acknowledgements

Acknowledgement that should also be removed.
"""

    out = pipe.postprocess_nature_markdown(markdown, remove_ref=True)

    assert "Main article conclusion." in out
    assert "## References" not in out
    assert "Reference that should be removed" not in out
    assert "## Acknowledgements" not in out
    assert "Acknowledgement that should also be removed" not in out


def test_postprocess_nature_markdown_keeps_references_when_configured() -> None:
    markdown = """# Example article title

## Abstract

Abstract text.

## References

1. Reference that should remain.
"""

    out = pipe.postprocess_nature_markdown(markdown, remove_ref=False)

    assert "## References" in out
    assert "Reference that should remain" in out
