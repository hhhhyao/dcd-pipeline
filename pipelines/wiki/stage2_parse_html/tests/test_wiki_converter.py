"""Tests for wiki-specific conversion passes.

Covers the preprocessing and postprocessing functions used by
:class:`~wp.converter.wiki.WikiMDConverter`, including infobox
normalisation, image alt-text generation, table cleanup, entity
decoding, and whitespace normalisation.
"""

from __future__ import annotations

from typing import cast

from lxml.html import (
    HtmlElement,
    document_fromstring,
    fragment_fromstring,
    tostring,
)

from parse_html.html_tool import PageMeta
from parse_html.html_tool.converter.md import (
    _expand_collapsed_table,
    _is_separator,
    _strip_trailing_empty_cells,
    normalize_whitespace,
    remove_void_list_items,
)
from parse_html.html_tool.converter.wiki import (
    _alt_from_src,
    clean_all_wiki_tables,
    clean_wiki_infoboxes,
    decode_img_alt_entities,
    generate_img_alt_from_filename,
    remove_empty_infobox_rows,
    remove_map_tables,
    strip_trailing_empty_cols,
    strip_zwnbsp,
)

# ── Infobox normalisation ─────────────────────────────────────────────


class TestRemoveEmptyInfoboxRows:
    INFOBOX_HTML = (
        "<div>"
        '<table class="infobox"><tbody>'
        '<tr><td colspan="2">Title</td></tr>'
        "<tr><td></td><td></td></tr>"
        "<tr><td>Born</td><td>1990</td></tr>"
        '<tr><td colspan="2"></td></tr>'
        "<tr><td>Died</td><td>2050</td></tr>"
        "</tbody></table>"
        "</div>"
    )

    def test_empty_rows_removed(self) -> None:
        tree = fragment_fromstring(self.INFOBOX_HTML)
        table = tree.xpath(".//table")[0]
        remove_empty_infobox_rows(table)
        rows = table.xpath(".//tr")
        texts = [r.text_content().strip() for r in rows]
        assert "" not in texts

    def test_clean_wiki_infoboxes_full(self) -> None:
        html = (
            "<html><body>"
            '<table class="infobox"><tbody>'
            '<tr><td colspan="2">Person Name</td></tr>'
            "<tr><td></td><td></td></tr>"
            "<tr><td>Born</td><td>1990</td></tr>"
            "</tbody></table>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        clean_wiki_infoboxes(tree)
        for row in cast(list[HtmlElement], tree.xpath(".//tr")):
            text = (row.text_content() or "").strip()
            assert text, "all-empty row should have been removed"


class TestStripTrailingEmptyCols:
    """Verify column-based stripping preserves table structure."""

    def test_entirely_empty_col_removed(self) -> None:
        html = (
            "<div>"
            '<table class="infobox"><tbody>'
            '<tr><td>Title</td><td></td></tr>'
            '<tr><td>A</td><td></td></tr>'
            "</tbody></table>"
            "</div>"
        )
        tree = fragment_fromstring(html)
        table = tree.xpath(".//table")[0]
        strip_trailing_empty_cols(table)
        for row in table.xpath(".//tr"):
            assert len(row.xpath("./td | ./th")) == 1

    def test_mixed_cols_preserved(self) -> None:
        """Don't strip col 2 if any row has content there."""
        html = (
            "<div>"
            '<table class="infobox"><tbody>'
            '<tr><td>Title</td><td></td></tr>'
            "<tr><td>A</td><td>B</td></tr>"
            '<tr><td>C</td><td></td></tr>'
            "</tbody></table>"
            "</div>"
        )
        tree = fragment_fromstring(html)
        table = tree.xpath(".//table")[0]
        strip_trailing_empty_cols(table)
        for row in table.xpath(".//tr"):
            assert len(row.xpath("./td | ./th")) == 2

    def test_consistent_col_count(self) -> None:
        """All rows should have equal column counts after stripping."""
        html = (
            "<div>"
            '<table class="infobox"><tbody>'
            '<tr><td>Section</td><td></td><td></td></tr>'
            "<tr><td>Key</td><td>Val</td><td></td></tr>"
            '<tr><td>X</td><td></td><td></td></tr>'
            "</tbody></table>"
            "</div>"
        )
        tree = fragment_fromstring(html)
        table = tree.xpath(".//table")[0]
        strip_trailing_empty_cols(table)
        counts = [
            len(r.xpath("./td | ./th"))
            for r in table.xpath(".//tr")
        ]
        assert all(c == 2 for c in counts)


class TestRemoveMapTables:
    """Verify DebutCarte map tables are replaced with map images."""

    MAP_HTML = (
        "<div>"
        '<table class="infobox"><tbody>'
        '<tr><td colspan="2">'
        '<table class="DebutCarte">'
        '<tr><td>'
        '<img alt="Map of France" src="france_map.jpg" width="280">'
        '<img alt="" src="locator_pin.svg" width="16">'
        "</td></tr>"
        "</table>"
        "</td></tr>"
        "</tbody></table>"
        "</div>"
    )

    def test_map_table_replaced_with_image(self) -> None:
        tree = fragment_fromstring(self.MAP_HTML)
        table = tree.xpath(".//table")[0]
        remove_map_tables(table)
        assert not tree.xpath(
            './/table[contains(@class, "DebutCarte")]',
        )
        imgs = tree.xpath(".//img")
        assert len(imgs) == 1
        assert imgs[0].get("alt") == "Map of France"

    def test_locator_pin_removed(self) -> None:
        tree = fragment_fromstring(self.MAP_HTML)
        table = tree.xpath(".//table")[0]
        remove_map_tables(table)
        for img in tree.xpath(".//img"):
            assert "locator" not in (img.get("src") or "")


class TestFransuInfobox:
    """Regression test for issue 20260225-051817-0cf4840c.

    The French Wikipedia commune infobox (e.g. Fransu) combines:
    - section header rows (``colspan="2"``, single ``<th>``)
    - key/value data rows (two cells)
    - DebutCarte map-positioning tables (nested, purely layout)
    - empty rows

    Before the fix, the markdown output had broken ``| --- |``
    separators mid-table, inconsistent column counts, and garbled
    map table remnants.
    """

    FRANSU_INFOBOX = (
        "<html><body>"
        '<table class="infobox_v2 infobox"><tbody>'
        # title row
        '<tr><td colspan="2">Fransu</td></tr>'
        # section header
        '<tr><th colspan="2">Administration</th></tr>'
        # data rows
        "<tr><th>Pays</th><td>France</td></tr>"
        "<tr><th>Région</th><td>Hauts-de-France</td></tr>"
        "<tr><th>Département</th><td>Somme</td></tr>"
        # section header
        '<tr><th colspan="2">Démographie</th></tr>'
        "<tr><th>Population</th><td>193 hab.</td></tr>"
        # section header
        '<tr><th colspan="2">Localisation</th></tr>'
        # DebutCarte map tables inside a single cell
        '<tr><td colspan="2">'
        '<div class="geobox">'
        '<table class="DebutCarte"><tbody>'
        "<tr><td>"
        '<img alt="Carte France" src="france_map.jpg" width="280">'
        '<img src="pin.svg" width="16">'
        "</td></tr>"
        "</tbody></table>"
        "</div>"
        '<div class="geobox">'
        '<table class="DebutCarte"><tbody>'
        "<tr><td>"
        '<img alt="Carte Somme" src="somme_map.jpg" width="280">'
        '<img src="pin.svg" width="16">'
        "</td></tr>"
        "</tbody></table>"
        "</div>"
        "</td></tr>"
        # empty row (should be removed)
        '<tr><td colspan="2"></td></tr>'
        # footer
        '<tr><td colspan="2">modifier</td></tr>'
        "</tbody></table>"
        "</body></html>"
    )

    def test_map_tables_removed(self) -> None:
        tree = document_fromstring(self.FRANSU_INFOBOX)
        clean_wiki_infoboxes(tree)
        assert not tree.xpath(
            './/table[contains(@class, "DebutCarte")]',
        )

    def test_map_images_preserved(self) -> None:
        tree = document_fromstring(self.FRANSU_INFOBOX)
        clean_wiki_infoboxes(tree)
        imgs = cast(list[HtmlElement], tree.xpath('.//table//img'))
        alts = [img.get("alt", "") for img in imgs]
        assert "Carte France" in alts
        assert "Carte Somme" in alts

    def test_locator_pins_removed(self) -> None:
        tree = document_fromstring(self.FRANSU_INFOBOX)
        clean_wiki_infoboxes(tree)
        for img in cast(list[HtmlElement], tree.xpath('.//table//img')):
            assert "pin" not in (img.get("src") or "")

    def test_empty_row_removed(self) -> None:
        tree = document_fromstring(self.FRANSU_INFOBOX)
        clean_wiki_infoboxes(tree)
        for row in cast(list[HtmlElement], tree.xpath(".//tr")):
            text = (row.text_content() or "").strip()
            has_img = bool(row.xpath(".//img"))
            assert text or has_img, (
                "row with no text and no images should be removed"
            )

    def test_consistent_column_count(self) -> None:
        tree = document_fromstring(self.FRANSU_INFOBOX)
        clean_wiki_infoboxes(tree)
        counts = [
            len(r.xpath("./td | ./th"))
            for r in cast(list[HtmlElement], tree.xpath(".//tr"))
        ]
        assert len(set(counts)) == 1, (
            f"all rows should have same column count, got {counts}"
        )

    def test_data_preserved(self) -> None:
        tree = document_fromstring(self.FRANSU_INFOBOX)
        clean_wiki_infoboxes(tree)
        tables = cast(list[HtmlElement], tree.xpath('.//table'))
        table = tables[0]
        text = table.text_content()
        assert "Fransu" in text
        assert "Hauts-de-France" in text
        assert "Somme" in text
        assert "193 hab." in text


class TestCleanAllWikiTables:
    def test_empty_rows_removed_from_non_infobox(self) -> None:
        html = (
            "<div>"
            '<table class="wikitable"><tbody>'
            "<tr><th>A</th><th>B</th></tr>"
            "<tr><td></td><td></td></tr>"
            "<tr><td>1</td><td>2</td></tr>"
            "</tbody></table>"
            "</div>"
        )
        tree = fragment_fromstring(html)
        clean_all_wiki_tables(tree)
        rows = tree.xpath(".//tr")
        assert len(rows) == 2
        assert "1" in rows[1].text_content()

    def test_rows_with_images_preserved(self) -> None:
        html = (
            "<div>"
            "<table><tbody>"
            '<tr><td><img src="x.png" alt="pic"></td></tr>'
            "<tr><td></td></tr>"
            "</tbody></table>"
            "</div>"
        )
        tree = fragment_fromstring(html)
        clean_all_wiki_tables(tree)
        rows = tree.xpath(".//tr")
        assert len(rows) == 1
        assert rows[0].xpath(".//img")


# ── Image alt-text generation ─────────────────────────────────────────


class TestAltFromSrc:
    def test_flag_url(self) -> None:
        src = (
            "//upload.wikimedia.org/wikipedia/commons/thumb/"
            "c/c1/Flag_of_Hungary.svg/60px-Flag_of_Hungary.svg.png"
        )
        assert _alt_from_src(src) == "Flag of Hungary"

    def test_simple_image(self) -> None:
        assert (
            _alt_from_src("//example.com/My_Photo.jpg") == "My Photo"
        )

    def test_url_encoded(self) -> None:
        src = "//example.com/Caf%C3%A9_menu.png"
        assert _alt_from_src(src) == "Café menu"

    def test_empty_src(self) -> None:
        assert _alt_from_src("") == ""

    def test_thumb_prefers_parent_segment(self) -> None:
        src = (
            "//upload.wikimedia.org/commons/thumb/"
            "a/b/Olympic_rings.svg/20px-Olympic_rings.svg.png"
        )
        assert _alt_from_src(src) == "Olympic rings"


class TestGenerateImgAlt:
    def test_sets_alt_on_missing(self) -> None:
        tree = fragment_fromstring(
            '<div>'
            '<img src="//example.com/Flag_of_Italy.svg">'
            '</div>',
        )
        generate_img_alt_from_filename(tree)
        img = tree.xpath(".//img")[0]
        assert img.get("alt") == "Flag of Italy"

    def test_preserves_existing_alt(self) -> None:
        tree = fragment_fromstring(
            '<div>'
            '<img src="//example.com/Foo.png" alt="Bar">'
            '</div>',
        )
        generate_img_alt_from_filename(tree)
        assert tree.xpath(".//img")[0].get("alt") == "Bar"

    def test_skips_empty_src(self) -> None:
        tree = fragment_fromstring('<div><img src=""></div>')
        generate_img_alt_from_filename(tree)
        assert tree.xpath(".//img")[0].get("alt") is None


class TestDecodeImgAltEntities:
    def test_amp_decoded(self) -> None:
        tree = fragment_fromstring(
            '<div>'
            '<img src="x.png" alt="Suit &amp; Tie">'
            '</div>',
        )
        decode_img_alt_entities(tree)
        assert tree.xpath(".//img")[0].get("alt") == "Suit & Tie"

    def test_no_entities_unchanged(self) -> None:
        tree = fragment_fromstring(
            '<div>'
            '<img src="x.png" alt="Normal text">'
            '</div>',
        )
        decode_img_alt_entities(tree)
        assert tree.xpath(".//img")[0].get("alt") == "Normal text"


# ── Invisible character removal ───────────────────────────────────────


class TestStripZwnbsp:
    def test_zwnbsp_removed_from_text(self) -> None:
        tree = fragment_fromstring(
            "<div><p>50°N\ufeff / \ufeff50.0°N</p></div>",
        )
        strip_zwnbsp(tree)
        result = tree.text_content()
        assert "\ufeff" not in result
        assert "50°N / 50.0°N" in result

    def test_zwnbsp_removed_from_tail(self) -> None:
        tree = fragment_fromstring(
            "<div><span>A</span>\ufeff tail</div>",
        )
        strip_zwnbsp(tree)
        assert "\ufeff" not in tostring(tree, encoding="unicode")

    def test_no_zwnbsp_unchanged(self) -> None:
        tree = fragment_fromstring("<div>Normal text</div>")
        strip_zwnbsp(tree)
        assert "Normal text" in tree.text_content()


# ── Markdown post-processing ──────────────────────────────────────────


class TestNormalizeWhitespace:
    def test_leading_newlines_stripped(self) -> None:
        text = "\n\n\n\nHello world"
        assert normalize_whitespace(text) == "Hello world"

    def test_excess_blanks_collapsed(self) -> None:
        text = "A\n\n\n\n\nB"
        assert normalize_whitespace(text) == "A\n\nB"

    def test_whitespace_only_lines_cleared(self) -> None:
        text = "A\n   \n  \nB"
        assert normalize_whitespace(text) == "A\n\nB"

    def test_html_entities_decoded(self) -> None:
        text = "Suit &amp; Tie"
        assert normalize_whitespace(text) == "Suit & Tie"

    def test_lt_gt_decoded(self) -> None:
        result = normalize_whitespace("a &lt; b &gt; c")
        assert result == "a < b > c"

    def test_nbsp_only_lines_cleared(self) -> None:
        """Lines containing only non-breaking spaces are blanked."""
        text = "A\n\xa0\n\xa0\nB"
        result = normalize_whitespace(text)
        assert "\xa0" not in result
        assert "A" in result
        assert "B" in result

    def test_nbsp_excessive_blanks_collapsed(self) -> None:
        r"""Multiple \xa0-only lines collapse to a single blank."""
        text = "A\n\xa0\n\xa0\n\xa0\n\xa0\nB"
        result = normalize_whitespace(text)
        assert result == "A\n\nB"


class TestRemoveVoidListItems:
    """Verify empty <li> elements are removed before serialisation."""

    def test_empty_li_removed(self) -> None:
        tree = fragment_fromstring(
            "<div><ul>"
            "<li></li>"
            "<li>Real item</li>"
            "</ul></div>",
        )
        remove_void_list_items(tree)
        lis = tree.xpath(".//li")
        assert len(lis) == 1
        assert lis[0].text_content() == "Real item"

    def test_whitespace_only_li_removed(self) -> None:
        tree = fragment_fromstring(
            "<div><ul>"
            "<li>   </li>"
            "<li>Content</li>"
            "</ul></div>",
        )
        remove_void_list_items(tree)
        lis = tree.xpath(".//li")
        assert len(lis) == 1

    def test_li_with_text_preserved(self) -> None:
        tree = fragment_fromstring(
            "<div><ul>"
            "<li>Item A</li>"
            "<li>Item B</li>"
            "</ul></div>",
        )
        remove_void_list_items(tree)
        assert len(tree.xpath(".//li")) == 2

    def test_li_with_image_preserved(self) -> None:
        """Empty text but containing <img> should be kept."""
        tree = fragment_fromstring(
            "<div><ul>"
            '<li><img src="icon.png" alt="icon"></li>'
            "<li></li>"
            "</ul></div>",
        )
        remove_void_list_items(tree)
        lis = tree.xpath(".//li")
        assert len(lis) == 1
        assert lis[0].xpath(".//img")

    def test_nested_empty_li_removed(self) -> None:
        tree = fragment_fromstring(
            "<div><ul>"
            "<li><ul><li></li></ul></li>"
            "<li>Keep</li>"
            "</ul></div>",
        )
        remove_void_list_items(tree)
        assert "Keep" in tree.text_content()
        for li in tree.xpath(".//li"):
            text = (li.text_content() or "").strip()
            has_img = bool(li.xpath(".//img"))
            assert text or has_img


class TestIsSeparator:
    """Verify _is_separator correctly identifies table separator rows."""

    def test_basic_separator(self) -> None:
        assert _is_separator("| --- | --- |")

    def test_aligned_separator(self) -> None:
        assert _is_separator("| :--- | ---: | :---: |")

    def test_long_dashes(self) -> None:
        assert _is_separator("| ------ | ---------- |")

    def test_data_row_not_separator(self) -> None:
        assert not _is_separator("| A | B |")

    def test_mixed_row_not_separator(self) -> None:
        assert not _is_separator("| --- | data |")

    def test_empty_not_separator(self) -> None:
        assert not _is_separator("")


class TestHeaderlessTables:
    """Tables starting with separator row get an empty header prepended."""

    def test_separator_first_gets_header(self) -> None:
        md = "| --- | --- |\n| A | B |"
        result = _strip_trailing_empty_cells(md)
        lines = [row for row in result.split("\n") if row.strip()]
        assert len(lines) == 3
        assert _is_separator(lines[1])
        assert not _is_separator(lines[0])

    def test_normal_table_unchanged(self) -> None:
        md = "| H1 | H2 |\n| --- | --- |\n| A | B |"
        result = _strip_trailing_empty_cells(md)
        lines = [row for row in result.split("\n") if row.strip()]
        assert len(lines) == 3
        assert not _is_separator(lines[0])
        assert _is_separator(lines[1])

    def test_headerless_table_renders_correct_cols(self) -> None:
        md = "| --- | --- | --- |\n| X | Y | Z |"
        result = _strip_trailing_empty_cells(md)
        lines = [row for row in result.split("\n") if row.strip()]
        header = lines[0]
        cols = [c.strip() for c in header.strip("|").split("|")]
        assert len(cols) == 3


class TestStripTrailingEmptyCells:
    def test_trailing_empty_cells_removed(self) -> None:
        md = (
            "| A | B |  |  |\n"
            "| --- | --- |  |  |\n"
            "| 1 | 2 |  |  |"
        )
        result = _strip_trailing_empty_cells(md)
        for line in result.split("\n"):
            assert not line.rstrip().endswith("|  |"), line

    def test_all_empty_row_removed(self) -> None:
        md = "| A |\n| --- |\n|  |\n| data |"
        result = _strip_trailing_empty_cells(md)
        assert "|  |" not in result
        assert "| data |" in result

    def test_non_table_lines_unchanged(self) -> None:
        md = "Hello world\n\nSome text |  |"
        result = _strip_trailing_empty_cells(md)
        assert "Hello world" in result
        assert "Some text |  |" in result


class TestExpandCollapsedTable:
    def test_basic_expansion(self) -> None:
        line = (
            "| Medal record | --- | "
            "| Gold | 1964 | | Silver | 1968 |"
        )
        rows = _expand_collapsed_table(line)
        assert rows is not None
        assert len(rows) >= 3
        assert "| Medal record |" in rows[0]
        assert "---" in rows[1]

    def test_no_separator_returns_none(self) -> None:
        line = "| A | B | C |"
        assert _expand_collapsed_table(line) is None

    def test_preserves_data(self) -> None:
        line = "| Header | --- | | val1 | val2 |"
        rows = _expand_collapsed_table(line)
        assert rows is not None
        joined = "\n".join(rows)
        assert "Header" in joined
        assert "val1" in joined
        assert "val2" in joined


class TestEntityDecoding:
    def test_amp_decoded(self) -> None:
        assert normalize_whitespace("A &amp; B") == "A & B"

    def test_lt_gt_decoded(self) -> None:
        result = normalize_whitespace("x &lt; y &gt; z")
        assert result == "x < y > z"

    def test_quot_decoded(self) -> None:
        result = normalize_whitespace("say &quot;hello&quot;")
        assert result == 'say "hello"'

    def test_real_ampersand_preserved(self) -> None:
        assert normalize_whitespace("A & B") == "A & B"


# ── Metadata URL handling ─────────────────────────────────────────────


class TestUrlEntityDecoding:
    def test_amp_in_url_decoded(self) -> None:
        html = (
            "<html><head>"
            '<link rel="canonical"'
            ' href="https://example.com/page?a=1&amp;b=2">'
            "</head><body><p>text</p></body></html>"
        )
        tree = document_fromstring(html)
        meta = PageMeta(tree)
        assert "&amp;" not in meta.url
        assert "a=1&b=2" in meta.url

    def test_url_kwarg_decoded(self) -> None:
        html = "<html><body><p>text</p></body></html>"
        tree = document_fromstring(html)
        meta = PageMeta(
            tree,
            url="https://example.com/page?a=1&amp;b=2",
        )
        assert meta.url == "https://example.com/page?a=1&b=2"

    def test_clean_url_unchanged(self) -> None:
        html = "<html><body><p>text</p></body></html>"
        tree = document_fromstring(html)
        meta = PageMeta(tree, url="https://example.com/page")
        assert meta.url == "https://example.com/page"
