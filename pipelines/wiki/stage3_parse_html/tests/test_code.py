"""Tests for code block normalisation."""

from __future__ import annotations

from lxml.html import document_fromstring, fragment_fromstring, tostring

from parse_html.html_tool import (
    PageMeta,
    make_cleaner,
    make_html_converter,
    make_md_converter,
)
from parse_html.html_tool.cleaner.page import normalize_code_blocks


class TestNormalizeCodeBlocks:
    def test_sphinx_highlight_div_becomes_pre_code(self) -> None:
        tree = fragment_fromstring(
            '<div>'
            '<div class="highlight-python notranslate">'
            '<div class="highlight"><pre>print("hello")</pre></div>'
            '</div>'
            '</div>',
        )
        normalize_code_blocks(tree)
        result = tostring(tree, encoding="unicode")
        assert '<pre><code class="language-python">' in result
        assert 'print("hello")' in result
        assert "highlight-python" not in result

    def test_extracts_language_from_class(self) -> None:
        tree = fragment_fromstring(
            '<div>'
            '<div class="highlight-javascript">'
            '<div class="highlight"><pre>const x = 1;</pre></div>'
            '</div>'
            '</div>',
        )
        normalize_code_blocks(tree)
        result = tostring(tree, encoding="unicode")
        assert 'class="language-javascript"' in result

    def test_preserves_code_text_content(self) -> None:
        code = "def foo():\n    return 42\n"
        tree = fragment_fromstring(
            '<div>'
            '<div class="highlight-python">'
            f'<div class="highlight"><pre>{code}</pre></div>'
            '</div>'
            '</div>',
        )
        normalize_code_blocks(tree)
        result = tostring(tree, encoding="unicode")
        assert "def foo():" in result
        assert "return 42" in result

    def test_ignores_divs_without_highlight_class(self) -> None:
        tree = fragment_fromstring(
            '<div>'
            '<div class="some-other-class">'
            '<div class="highlight"><pre>text</pre></div>'
            '</div>'
            '</div>',
        )
        normalize_code_blocks(tree)
        result = tostring(tree, encoding="unicode")
        assert "language-" not in result

    def test_preserves_tail_text(self) -> None:
        tree = fragment_fromstring(
            '<div>'
            '<div class="highlight-python">'
            '<div class="highlight"><pre>x = 1</pre></div>'
            '</div> following text'
            '</div>',
        )
        normalize_code_blocks(tree)
        result = tostring(tree, encoding="unicode")
        assert "following text" in result

    def test_no_pre_inside_is_skipped(self) -> None:
        tree = fragment_fromstring(
            '<div>'
            '<div class="highlight-python">'
            '<div class="highlight"><p>no pre here</p></div>'
            '</div>'
            '</div>',
        )
        normalize_code_blocks(tree)
        result = tostring(tree, encoding="unicode")
        assert "highlight-python" in result


class TestCodeBlockEndToEnd:
    def test_code_block_in_markdown(self) -> None:
        html = (
            "<html><head><title>Test</title></head><body>"
            '<div class="highlight-python notranslate">'
            '<div class="highlight"><pre>x = 42</pre></div>'
            '</div>'
            "</body></html>"
        )
        tree = document_fromstring(html)
        meta = PageMeta(tree)
        cleaner = make_cleaner(meta)
        meta, content = cleaner.clean(tree)
        converter = make_md_converter(meta)
        result = converter.convert(content)
        assert "x = 42" in result
        assert "```" in result

    def test_inline_code_in_markdown(self) -> None:
        html = (
            "<html><head><title>Test</title></head><body>"
            "<p>Use <code>print()</code> to output text.</p>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        meta = PageMeta(tree)
        cleaner = make_cleaner(meta)
        meta, content = cleaner.clean(tree)
        converter = make_md_converter(meta)
        result = converter.convert(content)
        assert "`print()`" in result

    def test_pre_code_in_html_converter(self) -> None:
        html = (
            "<html><head><title>Test</title></head><body>"
            "<pre><code>hello world</code></pre>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        meta = PageMeta(tree)
        cleaner = make_cleaner(meta)
        _, content = cleaner.clean(tree)
        converter = make_html_converter(meta)
        result = converter.convert(content)
        assert "<pre>" in result
        assert "<code>" in result
        assert "hello world" in result
