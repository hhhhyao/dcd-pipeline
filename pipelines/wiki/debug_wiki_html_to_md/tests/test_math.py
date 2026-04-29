"""Tests for math/LaTeX extraction and conversion."""

from __future__ import annotations

from lxml.html import fragment_fromstring, tostring

from parse_html.html_tool.converter.wiki import (
    convert_math_to_latex,
    extract_latex,
    strip_display_wrapper,
)


class TestExtractLatex:
    def test_from_annotation(self) -> None:
        tree = fragment_fromstring(
            '<span class="mwe-math-element">'
            '<math><semantics><annotation encoding="application/x-tex">'
            r'\alpha + \beta'
            '</annotation></semantics></math>'
            '</span>',
        )
        result = extract_latex(tree)
        assert result == r"\alpha + \beta"

    def test_fallback_to_img_alt(self) -> None:
        tree = fragment_fromstring(
            '<span class="mwe-math-element">'
            r'<img alt="\gamma" src="math.png">'
            '</span>',
        )
        result = extract_latex(tree)
        assert result == r"\gamma"

    def test_returns_none_when_no_source(self) -> None:
        tree = fragment_fromstring(
            '<span class="mwe-math-element">'
            '<img src="math.png">'
            '</span>',
        )
        result = extract_latex(tree)
        assert result is None

    def test_prefers_annotation_over_img_alt(self) -> None:
        tree = fragment_fromstring(
            '<span class="mwe-math-element">'
            '<math><semantics><annotation encoding="application/x-tex">'
            r'\delta'
            '</annotation></semantics></math>'
            r'<img alt="\epsilon" src="math.png">'
            '</span>',
        )
        result = extract_latex(tree)
        assert result == r"\delta"


class TestStripDisplayWrapper:
    def test_strips_displaystyle(self) -> None:
        assert strip_display_wrapper(r"{\displaystyle \beta }") == r"\beta"

    def test_strips_textstyle(self) -> None:
        assert strip_display_wrapper(r"{\textstyle x+y}") == "x+y"

    def test_leaves_plain_latex_unchanged(self) -> None:
        assert strip_display_wrapper(r"\alpha") == r"\alpha"

    def test_strips_whitespace(self) -> None:
        assert strip_display_wrapper("  x^2  ") == "x^2"


class TestConvertMathToLatex:
    def test_inline_math(self) -> None:
        tree = fragment_fromstring(
            '<div><p>The value '
            '<span class="mwe-math-element mwe-math-element-inline">'
            '<math><semantics><annotation encoding="application/x-tex">'
            r'\alpha'
            '</annotation></semantics></math>'
            '</span> is important.</p></div>',
        )
        convert_math_to_latex(tree)
        result = tostring(tree, encoding="unicode")
        assert r"$\alpha$" in result
        assert "mwe-math-element" not in result

    def test_display_math(self) -> None:
        tree = fragment_fromstring(
            '<div><p>'
            '<span class="mwe-math-element mwe-math-element-block">'
            '<math><semantics><annotation encoding="application/x-tex">'
            r'E = mc^2'
            '</annotation></semantics></math>'
            '</span>'
            '</p></div>',
        )
        convert_math_to_latex(tree)
        result = tostring(tree, encoding="unicode")
        assert "$$E = mc^2$$" in result

    def test_strips_displaystyle_wrapper(self) -> None:
        tree = fragment_fromstring(
            '<div><p>'
            '<span class="mwe-math-element mwe-math-element-inline">'
            '<math><semantics><annotation encoding="application/x-tex">'
            r'{\displaystyle \beta }'
            '</annotation></semantics></math>'
            '</span>'
            '</p></div>',
        )
        convert_math_to_latex(tree)
        result = tostring(tree, encoding="unicode")
        assert r"$\beta$" in result
        assert "displaystyle" not in result

    def test_preserves_surrounding_text(self) -> None:
        tree = fragment_fromstring(
            '<div><p>before '
            '<span class="mwe-math-element mwe-math-element-inline">'
            '<math><semantics><annotation encoding="application/x-tex">'
            'x'
            '</annotation></semantics></math>'
            '</span> after</p></div>',
        )
        convert_math_to_latex(tree)
        result = tostring(tree, encoding="unicode")
        assert "before" in result
        assert "$x$" in result
        assert "after" in result

    def test_skips_span_without_extractable_latex(self) -> None:
        tree = fragment_fromstring(
            '<div><p>'
            '<span class="mwe-math-element mwe-math-element-inline">'
            '<img src="math.png">'
            '</span>'
            '</p></div>',
        )
        convert_math_to_latex(tree)
        result = tostring(tree, encoding="unicode")
        assert "mwe-math-element" in result

    def test_multiple_math_elements(self) -> None:
        tree = fragment_fromstring(
            '<div><p>'
            '<span class="mwe-math-element mwe-math-element-inline">'
            '<math><semantics><annotation encoding="application/x-tex">'
            'a'
            '</annotation></semantics></math>'
            '</span> and '
            '<span class="mwe-math-element mwe-math-element-inline">'
            '<math><semantics><annotation encoding="application/x-tex">'
            'b'
            '</annotation></semantics></math>'
            '</span>'
            '</p></div>',
        )
        convert_math_to_latex(tree)
        result = tostring(tree, encoding="unicode")
        assert "$a$" in result
        assert "$b$" in result
        assert "mwe-math-element" not in result
