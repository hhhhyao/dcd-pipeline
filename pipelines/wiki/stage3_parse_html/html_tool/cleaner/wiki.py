"""Wiki-specific page cleaner.

:class:`WikiCleaner` extends :class:`PageCleaner` with extra passes
that remove MediaWiki noise (article message boxes, hidden spans).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lxml.html import HtmlElement
from lxml.html.builder import B, P

from .page import (
    HEADING_TAGS,
    PageCleaner,
    cls_xpath,
    remove_element,
    unwrap,
)

if TYPE_CHECKING:
    from ..meta import PageMeta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Section headings to strip when ``remove_ref`` is enabled.
# Case-insensitive.  Covers English and Chinese (simplified + traditional).
REF_HEADINGS = {
    # English
    "references", "notes", "external links",
    "further reading", "bibliography", "citations", "footnotes",
    "see also",
    # Chinese (simplified)
    "参考文献", "参考资料", "参考来源", "引用", "注释", "脚注",
    "外部链接", "外部連結", "延伸阅读", "参见",
    # Chinese (traditional)
    "參考文獻", "參考資料", "參考來源", "參考资料",
    "註釋", "注釋", "注释说明", "腳註", "延伸閱讀", "參見",
    "相關條目", "相关条目",
    # Japanese
    "参照", "出典", "外部リンク", "関連項目",
    # Korean
    "각주", "참고 문헌", "외부 링크",
    # German
    "einzelnachweise", "weblinks", "literatur", "anmerkungen",
    "fußnoten", "quellen",
    # French
    "références", "notes et références", "liens externes",
    "bibliographie",
    # Spanish
    "referencias", "notas", "enlaces externos",
    "bibliografía", "lecturas adicionales",
    "véase también",
    # Portuguese
    "referências", "ligações externas",
    "leitura adicional",
    # Russian
    "примечания", "ссылки", "литература", "библиография",
    # Italian
    "note", "collegamenti esterni", "voci correlate",
    "bibliografia",
    # Arabic (standard)
    "مراجع", "وصلات خارجية", "ملاحظات",
    # Egyptian Arabic
    "مصادر", "لينكات",
    # Dutch
    "referenties", "externe links", "bronnen", "voetnoten",
    # Polish
    "przypisy", "linki zewnętrzne",
    # Swedish
    "referenser", "externa länkar", "fotnoter",
    # Vietnamese
    "tham khảo", "liên kết ngoài", "chú thích",
    # Ukrainian
    "примітки", "посилання", "джерела", "література",
    # Persian
    "منابع", "پانویس", "پیوند به بیرون",
    # Cebuano
    "mga reperensya", "mga sumpay sa gawas",
    # Waray
    "mga sumpay ha gawas", "pinanbasaran",
}


# ---------------------------------------------------------------------------
# Heading utilities
# ---------------------------------------------------------------------------
def heading_level(el: HtmlElement) -> int | None:
    """Return the heading level (1-6) if *el* is a heading, else None.

    Also recognises MediaWiki heading wrappers such as
    ``<div class="mw-heading mw-heading2"><h2>…</h2></div>``.
    """
    tag = el.tag
    if isinstance(tag, str) and tag in HEADING_TAGS:
        return int(tag[1])
    # MediaWiki wraps headings in <div class="mw-heading mw-headingN">.
    classes = el.get("class", "").split()
    for cls in classes:
        if cls.startswith("mw-heading") and len(cls) == len("mw-heading") + 1:
            digit = cls[-1]
            if digit.isdigit():
                return int(digit)
    return None


def heading_text(el: HtmlElement) -> str:
    """Return the visible heading text for *el* (heading or wrapper)."""
    level = heading_level(el)
    if level is None:
        return ""
    # If el itself is h1-h6, use its text directly.
    if isinstance(el.tag, str) and el.tag in HEADING_TAGS:
        return (el.text_content() or "").strip()
    # mw-heading wrapper – find the inner h-tag.
    for child in el:
        if isinstance(child.tag, str) and child.tag in HEADING_TAGS:
            return (child.text_content() or "").strip()
    return (el.text_content() or "").strip()


def find_heading_container(content: HtmlElement) -> HtmlElement:
    """Find the container whose direct children include headings.

    May be *content* itself or a nested wrapper (e.g.
    ``div.mw-parser-output``).
    """
    container = content
    while True:
        children = list(container)
        if any(heading_level(c) is not None for c in children):
            break
        wrappers = [
            c for c in children
            if isinstance(c.tag, str) and c.tag in ("div", "section")
        ]
        if len(wrappers) == 1:
            container = wrappers[0]
        elif len(wrappers) > 1:
            heading_wrappers = [
                w for w in wrappers
                if any(heading_level(gc) is not None for gc in w)
            ]
            if len(heading_wrappers) == 1:
                container = heading_wrappers[0]
            else:
                # Multiple wrappers with headings (e.g. sibling
                # <section> elements) — stay at the current level.
                break
        else:
            break
    return container


# ---------------------------------------------------------------------------
# Wiki-cleaning passes
# ---------------------------------------------------------------------------
def remove_amboxes(tree: HtmlElement) -> None:
    """Remove Wikipedia article message boxes (editorial notices)."""
    for el in tree.xpath(
        f".//table[{cls_xpath('ambox')}] | .//*[{cls_xpath('mbox')}]"
    ):
        remove_element(el)


def remove_hidden_elements(tree: HtmlElement) -> None:
    """Remove elements with ``display:none`` or class ``mw-empty-elt``.

    The ``mw-empty-elt`` class marks empty placeholder elements that
    MediaWiki inserts (e.g. ``<p>``, ``<li>``).  When lxml serialises
    void ``<li>`` elements without closing tags, html-to-markdown
    mis-parses the resulting HTML and silently drops all subsequent
    content.  Removing them here prevents that.
    """
    for el in tree.xpath(
        ".//*[contains(@style,'display') and contains(@style,'none')]"
        f" | .//*[{cls_xpath('mw-empty-elt')}]"
    ):
        remove_element(el)


def remove_edit_sections(tree: HtmlElement) -> None:
    """Remove ``[edit]`` / ``[编辑]`` section-edit links."""
    for el in tree.xpath(f".//*[{cls_xpath('mw-editsection')}]"):
        remove_element(el)


def remove_magnify_links(tree: HtmlElement) -> None:
    """Remove thumbnail enlarge icons (``div.magnify``)."""
    for el in tree.xpath(f".//*[{cls_xpath('magnify')}]"):
        remove_element(el)


def unwrap_presentation_tables(tree: HtmlElement) -> None:
    """Unwrap ``<table role="presentation">`` layout wrappers.

    Wikipedia uses these to place content tables side-by-side (e.g.
    player squad lists).  The outer table, its ``<tbody>``, ``<tr>``,
    and ``<td>`` elements are all removed, leaving the inner content
    (typically real ``<table>`` elements) in place.
    """
    for table in tree.xpath('.//table[@role="presentation"]'):
        for td in table.xpath("./tbody/tr/td | ./tr/td"):
            unwrap(td)
        for tr in table.xpath("./tbody/tr | ./tr"):
            unwrap(tr)
        for tbody in table.xpath("./tbody"):
            unwrap(tbody)
        unwrap(table)


def remove_maintenance_tags(tree: HtmlElement) -> None:
    """Remove inline maintenance tags like ``[citation needed]``."""
    for sup in tree.xpath(f".//sup[{cls_xpath('Inline-Template')}]"):
        remove_element(sup)


def unwrap_dl_list_headers(tree: HtmlElement) -> None:
    """Convert ``<ul><li><dl><dt>…</dt></dl>…</ul>`` to ``<p><b>…</b></p>``.

    Wikipedia track listings wrap section headers like "CD single" in a
    ``<ul><li><dl><dt>`` structure.  The ``<ul><li>`` produces a stray
    ``-`` marker in Markdown followed by the ``<dt>`` content as a
    disconnected paragraph.  This pass replaces each such ``<ul>`` with a
    bold paragraph so it renders as a clean section label.
    """
    for ul in list(tree.iter("ul")):
        lis = ul.getchildren()
        if not lis or any(li.tag != "li" for li in lis):
            continue
        all_dl = True
        for li in lis:
            children = li.getchildren()
            if not children or any(c.tag != "dl" for c in children):
                all_dl = False
                break
            if (li.text or "").strip():
                all_dl = False
                break
        if not all_dl:
            continue

        parent = ul.getparent()
        if parent is None:
            continue
        idx = list(parent).index(ul)

        replacements: list[HtmlElement] = []
        for li in lis:
            for dl in li.getchildren():
                for dt in dl.getchildren():
                    if dt.tag == "dt":
                        p = P(B(dt.text or ""))
                        for child in dt:
                            p[0].append(child)
                        replacements.append(p)

        if replacements:
            replacements[-1].tail = ul.tail or ""
            parent.remove(ul)
            for i, rep in enumerate(replacements):
                parent.insert(idx + i, rep)


def remove_cs1_errors(tree: HtmlElement) -> None:
    """Remove CS1 citation error messages (hidden by CSS on Wikipedia).

    These are ``<span class="cs1-hidden-error citation-comment">`` and
    ``<span class="cs1-visible-error">`` elements that render template
    maintenance messages like ``{{cite book}}: CS1 maint: ...``.
    """
    xpath = (
        f".//*[{cls_xpath('cs1-hidden-error')}"
        f" or {cls_xpath('cs1-visible-error')}"
        f" or {cls_xpath('cs1-maint')}]"
    )
    for el in tree.xpath(xpath):
        remove_element(el)


def remove_stub_notices(tree: HtmlElement) -> None:
    """Remove stub article notices and category links."""
    xpath = f".//*[{cls_xpath('stub')} and {cls_xpath('asbox')}]"
    for el in tree.xpath(xpath):
        remove_element(el)
    for el in tree.xpath(f".//*[{cls_xpath('catlinks')}]"):
        remove_element(el)


def remove_taxobox_edit_icons(tree: HtmlElement) -> None:
    """Remove taxonomy-box edit pencil icons in Chinese Wikipedia.

    These are ``<span class="plainlinks taxobox-edit-taxonomy ...">``
    elements containing a pencil icon image with alt="编辑".
    """
    for el in tree.xpath(
        f".//*[{cls_xpath('taxobox-edit-taxonomy')}]"
    ):
        remove_element(el)


def remove_noprint_elements(tree: HtmlElement) -> None:
    """Remove elements with the ``noprint`` class.

    MediaWiki marks content that should not appear outside of the web
    view (succession boxes, portal bars, infobox navigation footers,
    short-description metadata, etc.) with ``class="noprint"``.  These
    produce junk navigation text and broken bold formatting in Markdown.

    Must run **before** :func:`unwrap_presentation_tables` so that
    ``<table class="succession-box noprint" role="presentation">``
    tables are removed entirely rather than unwrapped.
    """
    for el in tree.xpath(f".//*[{cls_xpath('noprint')}]"):
        if el.getparent() is not None:
            remove_element(el)


def apply_wiki_passes(tree: HtmlElement) -> None:
    """Run all wiki-specific cleaning passes in-place on *tree*."""
    remove_amboxes(tree)
    remove_edit_sections(tree)
    remove_hidden_elements(tree)
    remove_noprint_elements(tree)
    remove_magnify_links(tree)
    remove_maintenance_tags(tree)
    remove_cs1_errors(tree)
    remove_stub_notices(tree)
    remove_taxobox_edit_icons(tree)
    unwrap_presentation_tables(tree)
    unwrap_dl_list_headers(tree)


# ---------------------------------------------------------------------------
# Reference / notes removal (optional, controlled by meta.remove_ref)
# ---------------------------------------------------------------------------
def remove_citation_superscripts(content: HtmlElement) -> None:
    """Strip inline citation markers.

    Removes two kinds of ``<sup>`` elements:

    * ``<sup class="reference">`` – numbered citations like
      ``[1]``, ``[2]``, …
    * ``<sup class="Inline-Template">`` – maintenance tags like
      ``[citation needed]``, ``[clarification needed]``, etc.
    """
    xpath = (
        f".//sup[{cls_xpath('reference')}"
        f" or {cls_xpath('Inline-Template')}]"
    )
    for sup in content.xpath(xpath):
        remove_element(sup)


_HEADING_XPATH = (
    "./h1 | ./h2 | ./h3 | ./h4 | ./h5 | ./h6"
    " | ./div[contains(@class, 'mw-heading')]"
)

_DEEP_HEADING_XPATH = (
    ".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6"
    " | .//div[contains(@class, 'mw-heading')]"
)


def _walk_and_remove_ref_sections(
    container: HtmlElement,
    headings: list[HtmlElement],
) -> None:
    """Remove ref-heading siblings from *container* using *headings*."""
    to_remove: list[HtmlElement] = []

    for heading in headings:
        if heading.getparent() is None:
            continue
        text = heading_text(heading).lower()
        if text not in REF_HEADINGS:
            continue

        level = heading_level(heading)
        if level is None:
            continue

        parent = heading.getparent()
        assert parent is not None

        # If the heading lives inside a <section> wrapper, remove
        # the entire <section>.
        if parent.tag == "section":
            to_remove.append(parent)
            continue

        # If inside an intermediate wrapper div (e.g. references-small),
        # remove the wrapper and its next siblings up to the next
        # same-or-higher heading.
        if parent is not container:
            to_remove.append(parent)
            sib = parent.getnext()
            while sib is not None:
                # Check if sib contains a heading of same or higher level
                sib_headings = sib.xpath(_DEEP_HEADING_XPATH)
                stop = False
                for sh in sib_headings:
                    sl = heading_level(sh)
                    if sl is not None and sl <= level:
                        stop = True
                        break
                if stop:
                    break
                to_remove.append(sib)
                sib = sib.getnext()
            continue

        # Flat layout: heading is a direct child of container.
        to_remove.append(heading)
        sib = heading.getnext()
        while sib is not None:
            sib_level = heading_level(sib)
            if sib_level is not None and sib_level <= level:
                break
            to_remove.append(sib)
            sib = sib.getnext()

    for el in to_remove:
        if el.getparent() is not None:
            remove_element(el)


def remove_reference_sections(content: HtmlElement) -> None:
    """Remove reference / notes / external-links sections.

    Uses XPath to locate heading elements within the container,
    checks each heading's text against :data:`REF_HEADINGS`, then
    walks forward siblings to collect the entire section body for
    removal.  Also strips inline citation superscripts from the
    remaining text.

    Handles flat layouts (headings as direct children), HTML5
    sectioned layouts (headings inside ``<section>``), and
    headings nested inside wrapper divs.
    """
    remove_citation_superscripts(content)

    container = find_heading_container(content)
    all_headings: list[HtmlElement] = container.xpath(
        _DEEP_HEADING_XPATH,
    )
    _walk_and_remove_ref_sections(container, all_headings)


# ---------------------------------------------------------------------------
# Empty-section removal
# ---------------------------------------------------------------------------
def remove_empty_sections(content: HtmlElement) -> None:
    """Remove heading elements that introduce empty sections.

    A section is considered empty when there is no non-heading content
    between the heading and the next heading of the same or higher
    level (or the end of the parent container).  Runs repeatedly
    until no more empty sections remain, handling nested empty
    subsections.

    Handles both plain headings (``<h2>…</h2>``) and MediaWiki-style
    wrappers (``<div class="mw-heading"><h2>…</h2></div>``).
    """
    container = find_heading_container(content)

    changed = True
    while changed:
        changed = False
        for node in list(container):
            level = heading_level(node)
            if level is None:
                continue

            if node.getparent() is None:
                continue  # already removed

            # Non-whitespace tail text counts as content.
            if (node.tail or "").strip():
                continue

            # Walk following siblings within this section.
            section_empty = True
            sibling = node.getnext()
            while sibling is not None:
                sib_level = heading_level(sibling)
                if sib_level is not None:
                    # Same or higher level heading ends the section.
                    if sib_level <= level:
                        break
                    # Lower-level heading is part of this section.
                    if (sibling.tail or "").strip():
                        section_empty = False
                        break
                    sibling = sibling.getnext()
                    continue

                # Any non-heading element means section has content.
                section_empty = False
                break

            if section_empty:
                remove_element(node)
                changed = True


# ---------------------------------------------------------------------------
# WikiCleaner – PageCleaner with wiki-specific extra passes
# ---------------------------------------------------------------------------
class WikiCleaner(PageCleaner):
    """PageCleaner subclass that also removes MediaWiki-specific noise.

    Differences from the base pipeline:

    * Social-media links are **kept** – Wikipedia "External links"
      sections contain legitimate Facebook / YouTube / etc. entries
      whose text should survive ``unwrap_links``.

    Extra operations (run after the base pipeline):

    1. **Article message boxes** – ``table.ambox`` / ``.mbox``
       (editorial notices like "needs more sources") are removed.
    2. **Hidden spans** – ``display:none`` elements are removed.
    3. **Edit-section links** – ``[edit]`` / ``[编辑]`` are removed.
    """

    def __init__(self, meta: PageMeta) -> None:
        """Initialise with social-link preservation enabled."""
        super().__init__(meta, skip_social=True)

    def clean(self, tree: HtmlElement) -> tuple[PageMeta, HtmlElement]:
        """Run cleaning pipeline with wiki-specific adjustments."""
        meta, content = super().clean(tree)
        apply_wiki_passes(content)
        if meta.remove_ref:
            remove_reference_sections(content)
        remove_empty_sections(content)
        return meta, content
