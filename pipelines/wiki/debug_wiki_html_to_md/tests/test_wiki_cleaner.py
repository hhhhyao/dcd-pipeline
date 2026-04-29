"""Tests for wiki-specific cleaning passes."""

from __future__ import annotations

from lxml.html import (
    HtmlElement,
    document_fromstring,
    fragment_fromstring,
    tostring,
)

from parse_html.html_tool.cleaner.wiki import (
    apply_wiki_passes,
    remove_citation_superscripts,
    remove_hidden_elements,
    remove_magnify_links,
    remove_maintenance_tags,
    remove_noprint_elements,
    remove_reference_sections,
    unwrap_dl_list_headers,
    unwrap_presentation_tables,
)


class TestRemoveMagnifyLinks:
    """Verify that thumbnail enlarge icons are stripped."""

    def test_magnify_div_removed(self) -> None:
        tree = fragment_fromstring(
            "<div>"
            '<div class="thumbinner">'
            '<a href="/wiki/File:Map.svg"><img src="map.png" alt="Map"></a>'
            '<div class="thumbcaption">'
            '<div class="magnify">'
            '<a href="/wiki/File:Map.svg">class=notpageimage| </a>'
            "</div>"
            "Caption text"
            "</div>"
            "</div>"
            "</div>",
        )
        remove_magnify_links(tree)
        result = tostring(tree, encoding="unicode")
        assert "magnify" not in result
        assert "notpageimage" not in result
        assert "Caption text" in result
        assert 'src="map.png"' in result

    def test_apply_wiki_passes_removes_magnify(self) -> None:
        html = (
            "<html><body>"
            '<div class="thumbcaption">'
            '<div class="magnify">'
            '<a href="/wiki/File:X.svg">enlarge</a>'
            "</div>"
            "A caption."
            "</div>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        apply_wiki_passes(tree)
        result = tostring(tree, encoding="unicode")
        assert "magnify" not in result
        assert "A caption." in result


class TestUnwrapPresentationTables:
    """Verify that layout-only tables are unwrapped."""

    SIDE_BY_SIDE = (
        "<div>"
        '<table role="presentation" border="0"><tbody><tr>'
        "<td>"
        '<table class="wikitable"><tr>'
        "<th>No.</th><th>Player</th>"
        "</tr><tr>"
        "<td>1</td><td>Alice</td>"
        "</tr></table>"
        "</td>"
        "<td>"
        '<table class="wikitable"><tr>'
        "<th>No.</th><th>Player</th>"
        "</tr><tr>"
        "<td>2</td><td>Bob</td>"
        "</tr></table>"
        "</td>"
        "</tr></tbody></table>"
        "</div>"
    )

    def test_presentation_table_unwrapped(self) -> None:
        tree = fragment_fromstring(self.SIDE_BY_SIDE)
        unwrap_presentation_tables(tree)
        result = tostring(tree, encoding="unicode")
        assert 'role="presentation"' not in result
        assert "<tbody>" not in result
        assert "<td>Alice</td>" in result
        assert "<td>Bob</td>" in result

    def test_inner_tables_preserved(self) -> None:
        tree = fragment_fromstring(self.SIDE_BY_SIDE)
        unwrap_presentation_tables(tree)
        assert len(tree.xpath(".//table")) == 2

    def test_regular_tables_untouched(self) -> None:
        html = (
            "<div>"
            '<table class="wikitable"><tr>'
            "<th>A</th><th>B</th>"
            "</tr></table>"
            "</div>"
        )
        tree = fragment_fromstring(html)
        unwrap_presentation_tables(tree)
        result = tostring(tree, encoding="unicode")
        assert "<table" in result
        assert "<th>A</th>" in result

    def test_apply_wiki_passes_unwraps(self) -> None:
        html = (
            "<html><body>"
            '<table role="presentation"><tbody><tr>'
            "<td><p>Content A</p></td>"
            "<td><p>Content B</p></td>"
            "</tr></tbody></table>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        apply_wiki_passes(tree)
        result = tostring(tree, encoding="unicode")
        assert 'role="presentation"' not in result
        assert "Content A" in result
        assert "Content B" in result


class TestRemoveMaintenanceTags:
    """Verify that [citation needed] and similar tags are stripped."""

    def test_citation_needed_removed(self) -> None:
        html = (
            "<html><body><p>Some claim."
            '<sup class="noprint Inline-Template Template-Fact">'
            "[<i><a>citation needed</a></i>]"
            "</sup>"
            " More text.</p></body></html>"
        )
        tree = document_fromstring(html)
        remove_maintenance_tags(tree)
        result = tostring(tree, encoding="unicode")
        assert "citation needed" not in result
        assert "Some claim." in result
        assert "More text." in result

    def test_apply_wiki_passes_strips_maintenance(self) -> None:
        html = (
            "<html><body><p>Fact."
            '<sup class="Inline-Template">'
            "[unreliable source]"
            "</sup></p></body></html>"
        )
        tree = document_fromstring(html)
        apply_wiki_passes(tree)
        result = tostring(tree, encoding="unicode")
        assert "unreliable source" not in result
        assert "Fact." in result

    def test_regular_sups_preserved(self) -> None:
        html = (
            "<html><body><p>"
            "E=mc<sup>2</sup></p></body></html>"
        )
        tree = document_fromstring(html)
        remove_maintenance_tags(tree)
        assert "2" in tostring(tree, encoding="unicode")


class TestRemoveHiddenElements:
    """Verify display:none and mw-empty-elt elements are stripped."""

    def test_display_none_removed(self) -> None:
        html = (
            "<html><body>"
            '<div style="display:none">hidden</div>'
            "<p>Visible text.</p>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        remove_hidden_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "hidden" not in result
        assert "Visible text." in result

    def test_mw_empty_elt_removed(self) -> None:
        html = (
            "<html><body>"
            '<p class="mw-empty-elt"></p>'
            "<p>Real content.</p>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        remove_hidden_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "mw-empty-elt" not in result
        assert "Real content." in result

    def test_mw_empty_elt_li_removed(self) -> None:
        """Empty <li class="mw-empty-elt"> elements are stripped."""
        html = (
            "<html><body><ul>"
            '<li class="mw-empty-elt"></li>'
            "<li>Real item</li>"
            "</ul></body></html>"
        )
        tree = document_fromstring(html)
        remove_hidden_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "mw-empty-elt" not in result
        assert "Real item" in result

    def test_visible_elements_preserved(self) -> None:
        html = (
            "<html><body>"
            '<div style="display:block">shown</div>'
            "</body></html>"
        )
        tree = document_fromstring(html)
        remove_hidden_elements(tree)
        assert "shown" in tostring(tree, encoding="unicode")


class TestRemoveNoprintElements:
    """Verify noprint-class elements are removed."""

    def test_succession_box_removed(self) -> None:
        html = (
            "<html><body>"
            '<table class="wikitable succession-box noprint"'
            ' role="presentation">'
            "<tr><td>Previous race: Grand Prix A</td>"
            "<td>Next race: Grand Prix B</td></tr>"
            "</table>"
            "<p>Article content.</p>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        remove_noprint_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "succession-box" not in result
        assert "Previous race" not in result
        assert "Article content." in result

    def test_portal_bar_removed(self) -> None:
        html = (
            "<html><body>"
            '<div class="portal-bar noprint metadata">'
            "Portals: Science Technology"
            "</div>"
            "<p>Main text.</p>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        remove_noprint_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "portal-bar" not in result
        assert "Main text." in result

    def test_short_description_removed(self) -> None:
        html = (
            "<html><body>"
            '<span class="shortdescription nomobile noprint">'
            "A short description"
            "</span>"
            "<p>Body text.</p>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        remove_noprint_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "shortdescription" not in result
        assert "Body text." in result

    def test_infobox_nav_footer_removed(self) -> None:
        html = (
            "<html><body>"
            '<table class="infobox"><tbody>'
            "<tr><th>Born</th><td>1990</td></tr>"
            '<tr class="noprint"><td colspan="2">'
            '<a href="/prev">← 2019</a>'
            '<a href="/next">2021 →</a>'
            "</td></tr>"
            "</tbody></table>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        remove_noprint_elements(tree)
        result = tostring(tree, encoding="unicode")
        assert "Born" in result
        assert "1990" in result
        assert "← 2019" not in result
        assert "2021 →" not in result

    def test_non_noprint_preserved(self) -> None:
        html = (
            "<html><body>"
            '<div class="content">Real content</div>'
            "</body></html>"
        )
        tree = document_fromstring(html)
        remove_noprint_elements(tree)
        assert "Real content" in tostring(tree, encoding="unicode")

    def test_noprint_removed_before_unwrap(self) -> None:
        """Noprint presentation table is deleted, not unwrapped."""
        html = (
            "<html><body>"
            '<table class="noprint" role="presentation"><tbody><tr>'
            "<td>Nav content</td>"
            "</tr></tbody></table>"
            "<p>Article.</p>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        apply_wiki_passes(tree)
        result = tostring(tree, encoding="unicode")
        assert "Nav content" not in result
        assert "Article." in result


class TestUnwrapDlListHeaders:
    """Verify that <ul><li><dl><dt> section labels become <p><b>."""

    TRACK_HTML = (
        "<div>"
        "<ul><li><dl><dt>CD single</dt></dl></li></ul>"
        "<ol><li>Track 1</li><li>Track 2</li></ol>"
        "<ul><li><dl><dt>Digital download</dt></dl></li></ul>"
        "<ol><li>Track 3</li></ol>"
        "</div>"
    )

    def test_stray_dash_removed(self) -> None:
        tree = fragment_fromstring(self.TRACK_HTML)
        unwrap_dl_list_headers(tree)
        result = tostring(tree, encoding="unicode")
        assert "<ul>" not in result
        assert "<dl>" not in result

    def test_bold_paragraph_created(self) -> None:
        tree = fragment_fromstring(self.TRACK_HTML)
        unwrap_dl_list_headers(tree)
        result = tostring(tree, encoding="unicode")
        assert "<p><b>CD single</b></p>" in result
        assert "<p><b>Digital download</b></p>" in result

    def test_ordered_lists_preserved(self) -> None:
        tree = fragment_fromstring(self.TRACK_HTML)
        unwrap_dl_list_headers(tree)
        result = tostring(tree, encoding="unicode")
        assert "<ol>" in result
        assert "Track 1" in result
        assert "Track 3" in result

    def test_regular_ul_untouched(self) -> None:
        html = "<div><ul><li>Normal item</li></ul></div>"
        tree = fragment_fromstring(html)
        unwrap_dl_list_headers(tree)
        result = tostring(tree, encoding="unicode")
        assert "<ul>" in result
        assert "Normal item" in result

    def test_dt_children_preserved(self) -> None:
        """Inline elements like <sup> refs inside <dt> are kept."""
        html = (
            "<div>"
            "<ul><li><dl><dt>Title"
            '<sup class="reference">[1]</sup>'
            "</dt></dl></li></ul>"
            "</div>"
        )
        tree = fragment_fromstring(html)
        unwrap_dl_list_headers(tree)
        result = tostring(tree, encoding="unicode")
        assert "<b>Title" in result
        assert "[1]</sup>" in result

    def test_apply_wiki_passes_unwraps(self) -> None:
        html = (
            "<html><body>"
            "<ul><li><dl><dt>Section</dt></dl></li></ul>"
            "</body></html>"
        )
        tree = document_fromstring(html)
        apply_wiki_passes(tree)
        result = tostring(tree, encoding="unicode")
        assert "<ul>" not in result
        assert "<b>Section</b>" in result


# ---------------------------------------------------------------------------
# Helper to build a page with heading sections
# ---------------------------------------------------------------------------
def _wiki_content(*sections: tuple[str, int, str]) -> HtmlElement:
    """Build a content element with heading sections as direct children.

    Returns the container ``<div>`` whose direct children are the
    headings and body elements — matching what the cleaner pipeline
    passes to ``remove_reference_sections``.
    """
    parts = ["<div>"]
    for title, level, body in sections:
        parts.append(f"<h{level}>{title}</h{level}>")
        parts.append(body)
    parts.append("</div>")
    return fragment_fromstring("".join(parts))


def _mw_content(*sections: tuple[str, int, str]) -> HtmlElement:
    """Build a content element using MediaWiki mw-heading wrappers."""
    parts = ["<div>"]
    for title, level, body in sections:
        parts.append(
            f'<div class="mw-heading mw-heading{level}">'
            f"<h{level}>{title}</h{level}>"
            f"</div>",
        )
        parts.append(body)
    parts.append("</div>")
    return fragment_fromstring("".join(parts))


class TestRemoveCitationSuperscripts:
    """Verify inline citation markers are stripped."""

    def test_numbered_references_removed(self) -> None:
        html = (
            "<html><body><p>Claim"
            '<sup class="reference">[1]</sup>'
            " more text.</p></body></html>"
        )
        tree = document_fromstring(html)
        remove_citation_superscripts(tree)
        result = tostring(tree, encoding="unicode")
        assert "[1]" not in result
        assert "Claim" in result
        assert "more text." in result

    def test_multiple_refs_removed(self) -> None:
        html = (
            "<html><body><p>"
            'A<sup class="reference">[1]</sup>'
            'B<sup class="reference">[2]</sup>'
            'C<sup class="reference">[3]</sup>'
            "</p></body></html>"
        )
        tree = document_fromstring(html)
        remove_citation_superscripts(tree)
        result = tostring(tree, encoding="unicode")
        assert "reference" not in result
        assert "ABC" in result

    def test_inline_template_removed(self) -> None:
        html = (
            "<html><body><p>Fact."
            '<sup class="Inline-Template">[citation needed]</sup>'
            "</p></body></html>"
        )
        tree = document_fromstring(html)
        remove_citation_superscripts(tree)
        result = tostring(tree, encoding="unicode")
        assert "citation needed" not in result
        assert "Fact." in result

    def test_regular_sup_preserved(self) -> None:
        html = "<html><body><p>E=mc<sup>2</sup></p></body></html>"
        tree = document_fromstring(html)
        remove_citation_superscripts(tree)
        assert "<sup>2</sup>" in tostring(tree, encoding="unicode")


class TestRemoveReferenceSections:
    """Verify entire reference sections are removed."""

    def test_english_references_removed(self) -> None:
        el = _wiki_content(
            ("Introduction", 2, "<p>Article body.</p>"),
            ("References", 2, "<ol><li>Ref 1</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "Article body." in result
        assert "References" not in result
        assert "Ref 1" not in result

    def test_case_insensitive(self) -> None:
        el = _wiki_content(
            ("Content", 2, "<p>Body.</p>"),
            ("REFERENCES", 2, "<p>Ref data.</p>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "Body." in result
        assert "REFERENCES" not in result

    def test_chinese_simplified_cankaolaiyuan(self) -> None:
        el = _wiki_content(
            ("简介", 2, "<p>正文。</p>"),
            ("参考来源", 2, "<ol><li>来源1</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "正文。" in result
        assert "参考来源" not in result
        assert "来源1" not in result

    def test_chinese_traditional_cankaolaiyuan(self) -> None:
        el = _wiki_content(
            ("簡介", 2, "<p>正文。</p>"),
            ("參考來源", 2, "<ol><li>來源1</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "正文。" in result
        assert "參考來源" not in result

    def test_chinese_cankaowenxian(self) -> None:
        el = _wiki_content(
            ("内容", 2, "<p>正文。</p>"),
            ("参考文献", 2, "<ol><li>文献1</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "正文。" in result
        assert "参考文献" not in result

    def test_multiple_ref_sections_removed(self) -> None:
        el = _wiki_content(
            ("Content", 2, "<p>Body.</p>"),
            ("Notes", 2, "<p>Note 1.</p>"),
            ("References", 2, "<ol><li>Ref 1</li></ol>"),
            ("External links", 2, "<ul><li>Link 1</li></ul>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "Body." in result
        assert "Notes" not in result
        assert "References" not in result
        assert "External links" not in result

    def test_non_ref_sections_preserved(self) -> None:
        el = _wiki_content(
            ("History", 2, "<p>History content.</p>"),
            ("Geography", 2, "<p>Geography content.</p>"),
            ("References", 2, "<ol><li>Ref</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "History" in result
        assert "History content." in result
        assert "Geography" in result
        assert "Geography content." in result
        assert "References" not in result

    def test_subsection_removed_with_parent(self) -> None:
        """An h3 subsection under a matched h2 is also removed."""
        el = _wiki_content(
            ("Content", 2, "<p>Body.</p>"),
            ("References", 2, "<p>Intro refs.</p>"),
            ("Primary sources", 3, "<ol><li>Source 1</li></ol>"),
            ("Secondary sources", 3, "<ol><li>Source 2</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "Body." in result
        assert "References" not in result
        assert "Primary sources" not in result
        assert "Secondary sources" not in result

    def test_next_same_level_section_preserved(self) -> None:
        """A non-ref h2 after a ref h2 is kept."""
        el = _wiki_content(
            ("References", 2, "<ol><li>Ref</li></ol>"),
            ("Legacy", 2, "<p>Related pages.</p>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "References" not in result
        assert "Legacy" in result
        assert "Related pages." in result

    def test_mw_heading_wrapper(self) -> None:
        """Works with MediaWiki's div.mw-heading wrappers."""
        el = _mw_content(
            ("Content", 2, "<p>Body.</p>"),
            ("References", 2, "<ol><li>Ref 1</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "Body." in result
        assert "References" not in result
        assert "Ref 1" not in result

    def test_mw_heading_subsections(self) -> None:
        """MW-wrapped subsections under a ref heading are removed."""
        el = _mw_content(
            ("Content", 2, "<p>Body.</p>"),
            ("Notes", 2, "<p>Note text.</p>"),
            ("Footnotes", 3, "<ol><li>FN</li></ol>"),
            ("Further reading", 2, "<ul><li>Book</li></ul>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "Body." in result
        assert "Notes" not in result
        assert "Footnotes" not in result
        assert "Further reading" not in result

    def test_citation_superscripts_also_stripped(self) -> None:
        """Inline [1] refs in body text are removed alongside sections."""
        el = _wiki_content(
            (
                "Content", 2,
                '<p>Claim<sup class="reference">[1]</sup> more.</p>',
            ),
            ("References", 2, "<ol><li>Ref 1</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "[1]" not in result
        assert "Claim" in result
        assert "more." in result

    def test_no_ref_sections_noop(self) -> None:
        """When there are no ref headings, nothing is removed."""
        el = _wiki_content(
            ("History", 2, "<p>Past.</p>"),
            ("Geography", 2, "<p>Places.</p>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "History" in result
        assert "Past." in result
        assert "Geography" in result
        assert "Places." in result

    def test_german_einzelnachweise(self) -> None:
        el = _wiki_content(
            ("Inhalt", 2, "<p>Text.</p>"),
            ("Einzelnachweise", 2, "<ol><li>Ref</li></ol>"),
            ("Weblinks", 2, "<ul><li>Link</li></ul>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "Text." in result
        assert "Einzelnachweise" not in result
        assert "Weblinks" not in result

    def test_french_references(self) -> None:
        el = _wiki_content(
            ("Contenu", 2, "<p>Texte.</p>"),
            ("Références", 2, "<ol><li>Réf</li></ol>"),
            ("Liens externes", 2, "<ul><li>Lien</li></ul>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "Texte." in result
        assert "Références" not in result
        assert "Liens externes" not in result

    def test_japanese_references(self) -> None:
        el = _wiki_content(
            ("概要", 2, "<p>内容。</p>"),
            ("出典", 2, "<ol><li>出典1</li></ol>"),
            ("外部リンク", 2, "<ul><li>リンク</li></ul>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "内容。" in result
        assert ">出典<" not in result
        assert "外部リンク" not in result

    def test_see_also_removed(self) -> None:
        el = _wiki_content(
            ("Content", 2, "<p>Body.</p>"),
            ("See also", 2, "<ul><li>Related</li></ul>"),
            ("References", 2, "<ol><li>Ref</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "Body." in result
        assert "See also" not in result
        assert "References" not in result

    def test_chinese_see_also_removed(self) -> None:
        el = _wiki_content(
            ("内容", 2, "<p>正文。</p>"),
            ("参见", 2, "<ul><li>相关条目</li></ul>"),
            ("参考文献", 2, "<ol><li>文献</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "正文。" in result
        assert "参见" not in result
        assert "参考文献" not in result

    def test_chinese_yinyong_removed(self) -> None:
        """The heading '引用' (citations) is removed."""
        el = _wiki_content(
            ("生平", 2, "<p>生平内容。</p>"),
            ("引用", 2, "<ol><li>引用1</li></ol>"),
            ("外部链接", 2, "<ul><li>链接</li></ul>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "生平内容。" in result
        assert "引用" not in result
        assert "外部链接" not in result

    def test_mixed_script_cankaoziliao(self) -> None:
        """Mixed traditional/simplified '參考资料' is removed."""
        el = _wiki_content(
            ("生平概略", 2, "<p>内容。</p>"),
            ("參考资料", 2, "<ol><li>资料1</li></ol>"),
        )
        remove_reference_sections(el)
        result = tostring(el, encoding="unicode")
        assert "内容。" in result
        assert "參考资料" not in result
