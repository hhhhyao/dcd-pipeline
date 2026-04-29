"""Tests for nested-table extraction."""

from __future__ import annotations

from lxml.html import fragment_fromstring, tostring

from parse_html.html_tool.converter.md import flatten_nested_tables


def html_after(html: str) -> str:
    """Apply flatten_nested_tables and return the result HTML."""
    tree = fragment_fromstring(html)
    flatten_nested_tables(tree)
    result: str = tostring(tree, encoding="unicode")
    return result


class TestFlattenNestedTables:
    """Verify that tables inside cells are extracted."""

    def test_inner_table_extracted(self) -> None:
        html = (
            "<div>"
            "<table><tr><td>"
            "<table><tr><th>A</th></tr>"
            "<tr><td>1</td></tr></table>"
            "</td></tr></table>"
            "</div>"
        )
        result = html_after(html)
        assert result.count("<table>") == 2
        # Inner table should now be a sibling, not nested
        tree = fragment_fromstring(result)
        nested = tree.xpath(".//td//table")
        assert len(nested) == 0

    def test_inner_table_after_outer(self) -> None:
        html = (
            "<div>"
            "<table id='outer'><tr><td>"
            "<table id='inner'><tr><td>x</td></tr>"
            "</table>"
            "</td></tr></table>"
            "</div>"
        )
        tree = fragment_fromstring(html)
        flatten_nested_tables(tree)
        tables = tree.xpath(".//table")
        assert len(tables) == 2
        assert tables[0].get("id") == "outer"
        assert tables[1].get("id") == "inner"

    def test_top_level_table_untouched(self) -> None:
        html = (
            "<div>"
            "<table><tr><th>H</th></tr>"
            "<tr><td>V</td></tr></table>"
            "</div>"
        )
        result = html_after(html)
        assert "<table>" in result
        assert result.count("<table>") == 1

    def test_multi_level_nesting(self) -> None:
        html = (
            "<div>"
            "<table><tr><td>"
            "<table><tr><td>"
            "<table><tr><td>deep</td></tr></table>"
            "</td></tr></table>"
            "</td></tr></table>"
            "</div>"
        )
        result = html_after(html)
        assert "deep" in result
        assert result.count("<table>") == 3
        tree = fragment_fromstring(result)
        nested = tree.xpath(".//td//table")
        assert len(nested) == 0

    def test_cell_text_preserved(self) -> None:
        html = (
            "<div>"
            "<table><tr><td>"
            "before"
            "<table><tr><td>inner</td></tr></table>"
            "</td></tr></table>"
            "</div>"
        )
        result = html_after(html)
        assert "before" in result
        assert "inner" in result

    def test_multiple_nested_tables(self) -> None:
        html = (
            "<div>"
            "<table><tr>"
            "<td><table><tr><td>A</td></tr></table></td>"
            "<td><table><tr><td>B</td></tr></table></td>"
            "</tr></table>"
            "</div>"
        )
        result = html_after(html)
        assert result.count("<table>") == 3
        tree = fragment_fromstring(result)
        nested = tree.xpath(".//td//table")
        assert len(nested) == 0
