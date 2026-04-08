"""Tests for the parse_html pipe."""

from __future__ import annotations

import json
import re
from pathlib import Path

from dcd_cli.pipe import make_context

from .conftest import HTMLFixtureCase

PIPE_DIR = Path(__file__).resolve().parent.parent

VERSION_LINE_RE = re.compile(r"^version: .+\n", re.MULTILINE)

CTX = make_context("parse_html")


def load_pipe():
    """Import the pipe module and return its map function."""
    import parse_html as pipe_mod
    return pipe_mod


class TestManifest:
    def test_operation(self) -> None:
        from dcd_cli.pipe import PipeMan
        manifest = PipeMan.from_yaml(PIPE_DIR / "manifest.yaml")
        assert manifest.operation == "map"

    def test_input_fields(self) -> None:
        from dcd_cli.pipe import PipeMan
        manifest = PipeMan.from_yaml(PIPE_DIR / "manifest.yaml")
        text_in = manifest.input_fields["text"]
        assert "id" in text_in
        assert "data" in text_in
        assert "info" in text_in

    def test_output_fields(self) -> None:
        from dcd_cli.pipe import PipeMan
        manifest = PipeMan.from_yaml(PIPE_DIR / "manifest.yaml")
        text_out = manifest.output_fields["text"]
        assert "data" in text_out
        assert "info" in text_out


class TestMap:
    def test_simple_html(self) -> None:
        pipe = load_pipe()
        batch = {
            "id": ["1"],
            "info": ["{}"],
            "data": [
                "<html><head><title>Hello</title></head>"
                "<body><p>World</p></body></html>"
            ],
        }
        result = pipe.map(batch, CTX)
        out = result["data"][0]
        assert "World" in out
        assert "<html>" not in out
        out_info = json.loads(result["info"][0])
        assert out_info["format"] == "md"

    def test_empty_data_passthrough(self) -> None:
        pipe = load_pipe()
        batch = {"id": ["2"], "info": ["{}"], "data": [""]}
        result = pipe.map(batch, CTX)
        assert result["data"][0] == ""
        out_info = json.loads(result["info"][0])
        assert "format" not in out_info

    def test_out_format_html(self) -> None:
        pipe = load_pipe()
        ctx = make_context(
            "parse_html", config={"out_format": "html"},
        )
        batch = {
            "id": ["4"],
            "info": ["{}"],
            "data": [
                "<html><head><title>Hello</title></head>"
                "<body><p>World</p></body></html>"
            ],
        }
        result = pipe.map(batch, ctx)
        out = result["data"][0]
        assert "World" in out
        assert "<" in out
        out_info = json.loads(result["info"][0])
        assert out_info["format"] == "html"

    def test_remove_ref(self) -> None:
        pipe = load_pipe()
        ctx = make_context(
            "parse_html", config={"remove_ref": True},
        )
        batch = {
            "id": ["5"],
            "info": ["{}"],
            "data": [
                "<html><head><title>Test</title></head>"
                "<body><p>Content</p></body></html>"
            ],
        }
        result = pipe.map(batch, ctx)
        assert "Content" in result["data"][0]
        out_info = json.loads(result["info"][0])
        assert out_info["format"] == "md"


class TestTrailingEmptyCells:
    """Regression: regex catastrophic backtracking on wide tables."""

    def test_wide_table_no_hang(self) -> None:
        from parse_html.html_tool.converter.md import (
            normalize_whitespace,
        )

        row = (
            "| Country |  | | |  | | | 8 | 5 | 62.5% |"
            + " |  | |" * 12
            + " | 8 | 5 | 62.5% |"
        )
        table = "| A | B | C |\n| --- | --- | --- |\n" + row
        result = normalize_whitespace(table)
        assert "Country" in result
        assert "62.5%" in result


class TestRestoreLocalPaths:
    def test_strips_resolved_image_url(self) -> None:
        from parse_html import restore_local_paths

        text = (
            "![pic](https://en.wikipedia.org/wiki/images/abc.jpg)"
        )
        result = restore_local_paths(
            text, "https://en.wikipedia.org/wiki/Article",
        )
        assert result == "![pic](images/abc.jpg)"

    def test_noop_without_url(self) -> None:
        from parse_html import restore_local_paths

        text = "![pic](images/abc.jpg)"
        assert restore_local_paths(text, "") == text

    def test_preserves_unrelated_urls(self) -> None:
        from parse_html import restore_local_paths

        text = "![pic](https://cdn.example.com/photo.jpg)"
        result = restore_local_paths(
            text, "https://en.wikipedia.org/wiki/Article",
        )
        assert result == text

    def test_local_images_in_pipe_output(self) -> None:
        pipe = load_pipe()
        html = (
            '<html><body>'
            '<p>Text</p>'
            '<img src="images/abc123/photo.jpg" alt="A photo">'
            '</body></html>'
        )
        info = json.dumps(
            {"url": "https://en.wikipedia.org/wiki/Example"},
        )
        batch = {"id": ["1"], "info": [info], "data": [html]}
        result = pipe.map(batch, CTX)
        md = result["data"][0]
        assert "images/abc123/photo.jpg" in md
        assert "en.wikipedia.org/wiki/images" not in md


def test_fixture(html_fixture_case: HTMLFixtureCase) -> None:
    """Run the pipe against an HTML fixture case."""
    pipe = load_pipe()
    config = html_fixture_case.config or None
    ctx = make_context("parse_html", config=config)
    item = dict(html_fixture_case.input_item)
    item.setdefault("info", "{}")
    batch = {k: [v] for k, v in item.items()}
    result = pipe.map(batch, ctx)
    out_row = {k: v[0] for k, v in result.items()}
    out_row["data"] = VERSION_LINE_RE.sub("", out_row["data"])
    expected = html_fixture_case.expected_item
    actual = {k: out_row[k] for k in expected}
    assert actual == expected
