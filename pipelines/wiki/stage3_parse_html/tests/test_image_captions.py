"""Tests for image caption extraction from <figure>/<figcaption> pairs."""

from __future__ import annotations

from lxml.html import document_fromstring

from parse_html import extract_image_captions, run_extract_pipeline


class TestExtractImageCaptions:
    def test_basic_figure_with_caption(self) -> None:
        html = """<html><body>
        <figure>
          <img src="photo.jpg" alt="A sunset">
          <figcaption>A beautiful sunset over the ocean</figcaption>
        </figure>
        </body></html>"""
        tree = document_fromstring(html)
        result = extract_image_captions(tree)
        assert result == [
            {
                "url": "photo.jpg",
                "alt": "A sunset",
                "caption": "A beautiful sunset over the ocean",
            },
        ]

    def test_figure_without_caption_is_skipped(self) -> None:
        html = """<html><body>
        <figure>
          <img src="photo.jpg" alt="No caption">
        </figure>
        </body></html>"""
        tree = document_fromstring(html)
        assert extract_image_captions(tree) == []

    def test_figure_with_empty_caption_is_skipped(self) -> None:
        html = """<html><body>
        <figure>
          <img src="photo.jpg" alt="Empty caption">
          <figcaption>   </figcaption>
        </figure>
        </body></html>"""
        tree = document_fromstring(html)
        assert extract_image_captions(tree) == []

    def test_multiple_figures(self) -> None:
        html = """<html><body>
        <figure>
          <img src="a.jpg" alt="First">
          <figcaption>Caption A</figcaption>
        </figure>
        <figure>
          <img src="b.jpg" alt="Second">
          <figcaption>Caption B</figcaption>
        </figure>
        </body></html>"""
        tree = document_fromstring(html)
        result = extract_image_captions(tree)
        assert len(result) == 2
        assert result[0]["url"] == "a.jpg"
        assert result[0]["caption"] == "Caption A"
        assert result[1]["url"] == "b.jpg"
        assert result[1]["caption"] == "Caption B"

    def test_multiple_images_in_one_figure(self) -> None:
        html = """<html><body>
        <figure>
          <img src="a.jpg" alt="First">
          <img src="b.jpg" alt="Second">
          <figcaption>Two images</figcaption>
        </figure>
        </body></html>"""
        tree = document_fromstring(html)
        result = extract_image_captions(tree)
        assert len(result) == 2
        assert result[0] == {
            "url": "a.jpg", "alt": "First",
            "caption": "Two images",
        }
        assert result[1] == {
            "url": "b.jpg", "alt": "Second",
            "caption": "Two images",
        }

    def test_image_without_alt(self) -> None:
        html = """<html><body>
        <figure>
          <img src="photo.jpg">
          <figcaption>No alt text</figcaption>
        </figure>
        </body></html>"""
        tree = document_fromstring(html)
        result = extract_image_captions(tree)
        assert result == [
            {
                "url": "photo.jpg", "alt": "",
                "caption": "No alt text",
            },
        ]

    def test_image_without_src_is_skipped(self) -> None:
        html = """<html><body>
        <figure>
          <img alt="No src">
          <figcaption>Has caption but no src</figcaption>
        </figure>
        </body></html>"""
        tree = document_fromstring(html)
        assert extract_image_captions(tree) == []

    def test_no_figures_returns_empty(self) -> None:
        html = "<html><body><p>Just text</p></body></html>"
        tree = document_fromstring(html)
        assert extract_image_captions(tree) == []

    def test_figcaption_with_nested_markup(self) -> None:
        html = """<html><body>
        <figure>
          <img src="chart.png" alt="Chart">
          <figcaption>Figure 1: <em>Sales</em> by
          <strong>region</strong></figcaption>
        </figure>
        </body></html>"""
        tree = document_fromstring(html)
        result = extract_image_captions(tree)
        assert result[0]["caption"] == "Figure 1: Sales by region"


class TestPipelineImageCaptions:
    def test_captions_in_extract_result(self) -> None:
        html = """<html><body>
        <article>
          <p>Some text.</p>
          <figure>
            <img src="diagram.png" alt="Diagram">
            <figcaption>Architecture overview</figcaption>
          </figure>
        </article>
        </body></html>"""
        result = run_extract_pipeline(html, url="https://example.com")
        assert len(result.images) == 1
        assert result.images[0]["caption"] == "Architecture overview"

    def test_no_captions_when_no_figures(self) -> None:
        html = "<html><body><p>Plain text</p></body></html>"
        result = run_extract_pipeline(html)
        assert result.images == []
