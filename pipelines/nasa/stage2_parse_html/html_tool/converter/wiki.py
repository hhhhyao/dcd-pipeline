"""Wiki-specific Markdown converter.

:class:`WikiMDConverter` subclasses :class:`MarkdownConverter` for
wiki pages, adding infobox normalisation before the Markdown pass.
"""

from __future__ import annotations

import html as html_mod
import re
from urllib.parse import unquote

from lxml.html import HtmlElement
from lxml.html.builder import TD

from ..cleaner.page import cls_xpath, remove_element
from .md import MarkdownConverter, unwrap_sup_sub

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

# Matches CJK Unified Ideographs and common CJK ranges.
CJK_RE = re.compile(
    r"[\u4e00-\u9fff"       # CJK Unified Ideographs
    r"\u3400-\u4dbf"        # CJK Extension A
    r"\u3000-\u303f"        # CJK Symbols and Punctuation
    r"\u3040-\u309f"        # Hiragana
    r"\u30a0-\u30ff"        # Katakana
    r"\uac00-\ud7af]",      # Hangul Syllables
)

# Matches {\displaystyle ...} or {\textstyle ...} wrappers in LaTeX.
DISPLAY_WRAPPER_RE = re.compile(
    r"^\{\\(?:displaystyle|textstyle)\s+(.*)\}$",
    re.DOTALL,
)


def is_cjk_text(text: str) -> bool:
    """Return True if *text* contains predominantly CJK characters."""
    if not text:
        return False
    cjk_count = len(CJK_RE.findall(text))
    alpha_count = sum(1 for c in text if c.isalpha())
    return alpha_count > 0 and cjk_count / alpha_count > 0.5


class WikiMDConverter(MarkdownConverter):
    """Converter for wiki pages.

    Adds an infobox normalisation pre-processing step that replaces
    indicator images with Unicode arrows and formats list items as
    Markdown lists.
    """

    def convert(self, tree: HtmlElement) -> str:
        """Normalise wiki tables in-place, then convert to Markdown."""
        convert_math_to_latex(tree)
        unwrap_sup_sub(tree)
        unwrap_mw_file_spans(tree)
        clean_wiki_infoboxes(tree)
        clean_all_wiki_tables(tree)
        generate_img_alt_from_filename(tree)
        decode_img_alt_entities(tree)
        strip_zwnbsp(tree)
        return super().convert(tree)


def unwrap_mw_file_spans(tree: HtmlElement) -> None:
    """Unwrap ``<span typeof="mw:File">`` wrappers added by MediaWiki.

    These decorative spans (often carrying ``class="notpageimage"``)
    confuse the markdown converter, which renders the class attribute
    as link text.  Unwrapping keeps the inner ``<a>``/``<img>`` intact.
    """
    from ..cleaner.page import unwrap

    for span in list(tree.xpath('.//span[@typeof="mw:File"]')):
        unwrap(span)


# ---------------------------------------------------------------------------
# Image alt-text generation
# ---------------------------------------------------------------------------

_THUMB_SIZE_RE = re.compile(r"/\d+px-")


def _alt_from_src(src: str) -> str:
    """Derive a human-readable alt from an image URL.

    ``//upload.wikimedia.org/.../Flag_of_Hungary.svg/60px-Flag_of_Hungary.svg.png``
    → ``"Flag of Hungary"``
    """
    # Strip query params / fragments
    path = src.split("?")[0].split("#")[0]
    # Take last path segment, or the one before the thumbnail variant
    parts = path.rstrip("/").split("/")
    name = parts[-1] if parts else ""
    # If the last segment is a thumbnail (e.g. "60px-Flag_of_Hungary.svg.png"),
    # try the segment before it for a cleaner name
    if _THUMB_SIZE_RE.search("/" + name) and len(parts) >= 2:
        name = parts[-2]
    # URL-decode, strip extension, replace underscores
    name = unquote(name)
    name = re.sub(r"\.\w{2,4}$", "", name)
    name = name.replace("_", " ").strip()
    return name


def generate_img_alt_from_filename(tree: HtmlElement) -> None:
    """Set ``alt`` on ``<img>`` elements that lack it, using the filename."""
    for img in tree.iter("img"):
        alt = (img.get("alt") or "").strip()
        if alt:
            continue
        src = img.get("src") or ""
        if not src:
            continue
        derived = _alt_from_src(src)
        if derived:
            img.set("alt", derived)


def decode_img_alt_entities(tree: HtmlElement) -> None:
    """Decode HTML entities in image ``alt`` attributes."""
    for img in tree.iter("img"):
        alt = img.get("alt") or ""
        if "&" in alt:
            img.set("alt", html_mod.unescape(alt))


# ---------------------------------------------------------------------------
# Strip invisible characters
# ---------------------------------------------------------------------------

_INVISIBLE_RE = re.compile(
    "[\ufeff\u200b\u200c\u200d\u200e\u200f"
    "\u202a\u202b\u202c\u202d\u202e\u2060\u2061\ufeff]"
)


def strip_zwnbsp(tree: HtmlElement) -> None:
    """Remove invisible Unicode characters from all text nodes.

    Strips zero-width spaces (U+200B), zero-width joiners,
    directional marks, word joiners, and BOM characters that
    leak from Wikipedia source HTML into the markdown output.
    """
    for el in tree.iter():
        if el.text and _INVISIBLE_RE.search(el.text):
            el.text = _INVISIBLE_RE.sub("", el.text)
        if el.tail and _INVISIBLE_RE.search(el.tail):
            el.tail = _INVISIBLE_RE.sub("", el.tail)


# ---------------------------------------------------------------------------
# Normalize table columns – Markdown tables don't support colspan
# ---------------------------------------------------------------------------
def normalize_table_cols(table: HtmlElement) -> None:
    """Expand ``colspan`` / ``rowspan`` and pad rows for Markdown tables.

    Markdown tables have no colspan or rowspan support, so this function
    converts them into a flat grid:

    1. **Expand colspan** – a cell with ``colspan="N"`` is turned into
       *N* cells (the original cell plus N−1 empty ``<td>`` siblings).
       This keeps column alignment correct.
    2. **Pad rows** – after expansion, short rows are padded with empty
       ``<td>`` elements so every row has the same number of cells.
    """
    rows = table.xpath(".//tr")
    for cell in table.xpath(".//*[self::th or self::td][@colspan]"):
        try:
            span = int(cell.get("colspan", "1"))
        except ValueError:
            span = 1
        del cell.attrib["colspan"]
        if span > 1:
            parent = cell.getparent()
            if parent is None:
                continue
            idx = list(parent).index(cell)
            for i in range(1, span):
                parent.insert(idx + i, TD())

    max_cols = max(
        (len(row.xpath("./td | ./th")) for row in rows),
        default=0,
    )
    if max_cols < 2:
        return
    for row in rows:
        cells = row.xpath("./td | ./th")
        for _ in range(max_cols - len(cells)):
            row.append(TD())


# ---------------------------------------------------------------------------
# Infobox normalisation (operates on already-cleaned tree)
# ---------------------------------------------------------------------------
def clean_wiki_infoboxes(tree: HtmlElement) -> None:
    """Normalize MediaWiki infobox tables for cleaner Markdown output.

    Applies fixes inside ``<table class="infobox">`` elements:

    1. **Nested subtables** – ``infobox-subbox`` tables nested inside
       ``<td>`` cells are hoisted: their rows are spliced into the
       parent table, replacing the row that contained the subtable.
    2. **Indicator images** – tiny Increase/Decrease arrow icons
       are replaced with Unicode arrows (↑/↓).
    3. **List items** – ``<li>`` inside ``infobox-data`` cells are
       joined with a comma.  The separator is chosen based on the
       cell text: ``"、"`` for CJK content, ``", "`` otherwise.
    4. **<br>-separated runs** – names or values separated by
       ``<br>`` inside data cells are collapsed into a single line
       using the same locale-aware separator.
    """
    for table in tree.xpath(f".//table[{cls_xpath('infobox')}]"):
        hoist_subtables(table)
        remove_map_tables(table)
        replace_indicator_arrows(table)
        join_list_items(table)
        collapse_br_runs(table)
        normalize_table_cols(table)
        remove_empty_infobox_rows(table)
        strip_trailing_empty_cols(table)


def remove_map_tables(table: HtmlElement) -> None:
    """Remove ``DebutCarte`` map-positioning tables from an infobox.

    French Wikipedia infoboxes embed ``<table class="DebutCarte">``
    tables to overlay a locator pin on a map image.  These are purely
    presentational and produce garbled markdown when converted.

    This function replaces each ``DebutCarte`` table with just its
    main map ``<img>`` element (the first image that isn't a tiny
    overlay icon), discarding the table structure.
    """
    for mt in list(table.xpath(
        f".//table[{cls_xpath('DebutCarte')}]"
    )):
        imgs = mt.xpath(".//img")
        main_img = None
        for img in imgs:
            w = img.get("width", "")
            try:
                if int(w) > 30:
                    main_img = img
                    break
            except (ValueError, TypeError):
                if not main_img:
                    main_img = img

        parent = mt.getparent()
        if parent is None:
            continue
        if main_img is not None:
            main_img.tail = mt.tail or ""
            parent.replace(mt, main_img)
        else:
            remove_element(mt)


def hoist_subtables(table: HtmlElement) -> None:
    """Hoist nested ``infobox-subbox`` tables into the parent table.

    Wikipedia infoboxes often embed a ``<table class="infobox-subbox">``
    inside a ``<td colspan="2">`` cell (e.g. the "Transcriptions" block
    in language infoboxes).  Markdown has no support for nested tables,
    so these get squashed into a single unreadable cell.

    This function finds each nested subtable, extracts its ``<tr>`` rows,
    and splices them into the parent table immediately after the row that
    contained the subtable.  The original wrapper row is removed if the
    cell had no other meaningful content.
    """
    for subtable in list(table.xpath(
        f".//table[{cls_xpath('infobox-subbox')}]"
    )):
        # Walk up: subtable → <td> → <tr> → <tbody>/<table>
        cell = subtable.getparent()
        if cell is None or cell.tag not in ("td", "th"):
            continue
        wrapper_row = cell.getparent()
        if wrapper_row is None or wrapper_row.tag != "tr":
            continue
        row_parent = wrapper_row.getparent()
        if row_parent is None:
            continue

        # Collect the subtable's rows.
        sub_rows = list(subtable.xpath(".//tr"))

        # Insert them after the wrapper row.
        insert_idx = list(row_parent).index(wrapper_row) + 1
        for i, sr in enumerate(sub_rows):
            row_parent.insert(insert_idx + i, sr)

        # Remove the subtable from the cell.
        cell.remove(subtable)

        # If the cell (and therefore its row) has no meaningful
        # text left, drop the wrapper row entirely.
        remaining = (cell.text_content() or "").strip()
        if not remaining:
            row_parent.remove(wrapper_row)


def replace_indicator_arrows(table: HtmlElement) -> None:
    """Replace Increase/Decrease/Steady indicator images with arrows."""
    arrow_map = {"increase": "↑", "decrease": "↓", "steady": "→"}
    for img in table.xpath(".//img"):
        alt = (img.get("alt") or "").lower()
        if alt in arrow_map:
            arrow = arrow_map[alt]
            parent = img.getparent()
            if parent is None:
                continue
            prev = img.getprevious()
            tail = img.tail or ""
            if prev is not None:
                prev.tail = (prev.tail or "") + arrow + tail
            else:
                parent.text = (parent.text or "") + arrow + tail
            parent.remove(img)


def join_list_items(table: HtmlElement) -> None:
    """Join ``<li>`` items in data cells with a locale-aware separator.

    Uses ``"、"`` for CJK content, ``", "`` otherwise.
    """
    for cell in table.xpath(f".//td[{cls_xpath('infobox-data')}]"):
        for ul in cell.xpath(".//ul | .//ol"):
            items = [
                li.text_content().strip()
                for li in ul.xpath(".//li")
            ]
            sample = " ".join(items)
            sep = "、" if is_cjk_text(sample) else ", "
            joined = sep.join(items)
            parent = ul.getparent()
            if parent is None:
                continue
            prev = ul.getprevious()
            tail = ul.tail or ""
            if prev is not None:
                prev.tail = (prev.tail or "") + joined + tail
            else:
                parent.text = (parent.text or "") + joined + tail
            parent.remove(ul)


def collapse_br_runs(table: HtmlElement) -> None:
    """Collapse ``<br>``-separated text in data cells into one line.

    Uses ``"、"`` for CJK content, ``", "`` otherwise.
    """
    for cell in table.xpath(f".//td[{cls_xpath('infobox-data')}]"):
        if not cell.xpath(".//br"):
            continue
        segments: list[str] = []
        current = cell.text or ""
        for child in cell:
            if child.tag == "br":
                segments.append(current.strip())
                current = child.tail or ""
            else:
                current += child.text_content()
                current += child.tail or ""
        segments.append(current.strip())
        items = [s for s in segments if s]
        # Merge parenthetical qualifiers like "(2024)" into the
        # preceding item -- they are attributions, not list entries.
        merged: list[str] = []
        for item in items:
            if item.startswith("(") and merged:
                merged[-1] += " " + item
            else:
                merged.append(item)
        items = merged
        if len(items) < 2:
            continue
        sample = " ".join(items)
        sep = "、" if is_cjk_text(sample) else ", "
        cell.text = sep.join(items)
        for child in list(cell):
            cell.remove(child)


def remove_empty_infobox_rows(table: HtmlElement) -> None:
    """Remove ``<tr>`` rows in an infobox that have no visible content."""
    for row in list(table.xpath(".//tr")):
        text = (row.text_content() or "").strip()
        if not text and not row.xpath(".//img"):
            remove_element(row)


def strip_trailing_empty_cols(table: HtmlElement) -> None:
    """Remove trailing columns that are empty in every row.

    After ``normalize_table_cols`` pads rows to the same width, some
    trailing columns may be entirely empty.  Removing those columns
    keeps the table compact while preserving a consistent column count
    across all rows (which is required for valid markdown tables).
    """
    rows = table.xpath(".//tr")
    if not rows:
        return
    max_cols = max(
        (len(r.xpath("./td | ./th")) for r in rows), default=0,
    )
    if max_cols < 2:
        return

    keep = max_cols
    for col in range(max_cols - 1, 0, -1):
        col_empty = True
        for row in rows:
            cells = row.xpath("./td | ./th")
            if col < len(cells):
                cell = cells[col]
                text = (cell.text_content() or "").strip()
                if text or cell.xpath(".//img"):
                    col_empty = False
                    break
        if col_empty:
            keep = col
        else:
            break

    if keep < max_cols:
        for row in rows:
            cells = list(row.xpath("./td | ./th"))
            for cell in cells[keep:]:
                row.remove(cell)


def clean_all_wiki_tables(tree: HtmlElement) -> None:
    """Remove empty rows from all wiki tables (not just infoboxes)."""
    for table in tree.xpath(".//table"):
        for row in list(table.xpath(".//tr")):
            text = (row.text_content() or "").strip()
            if not text and not row.xpath(".//img"):
                remove_element(row)


# ---------------------------------------------------------------------------
# Math → LaTeX conversion (operates on already-cleaned tree)
# ---------------------------------------------------------------------------
def extract_latex(span: HtmlElement) -> str | None:
    """Extract LaTeX source from a ``mwe-math-element`` span.

    Prefers ``<annotation encoding="application/x-tex">`` inside the
    MathML block.  Falls back to the ``alt`` attribute of the fallback
    ``<img>`` element.
    """
    # Try <annotation encoding="application/x-tex"> first.
    annotations = span.xpath(
        ".//annotation[@encoding='application/x-tex']"
    )
    for ann in annotations:
        text = (ann.text or "").strip()
        if text:
            return text

    # Fallback: <img alt="...">
    for img in span.xpath(".//img"):
        alt = (img.get("alt") or "").strip()
        if alt:
            return alt

    return None


def strip_display_wrapper(latex: str) -> str:
    r"""Strip ``{\displaystyle ...}`` or ``{\textstyle ...}`` wrapper.

    >>> strip_display_wrapper(r"{\displaystyle \beta }")
    '\\beta'
    """
    m = DISPLAY_WRAPPER_RE.match(latex.strip())
    if m:
        return m.group(1).strip()
    return latex.strip()


def convert_math_to_latex(tree: HtmlElement) -> None:
    r"""Replace MediaWiki math spans with LaTeX ``$...$`` / ``$$...$$``.

    Each ``<span class="mwe-math-element">`` is replaced by a text
    node containing the LaTeX expression wrapped in dollar signs:

    * **Inline** (``mwe-math-element-inline``) → ``$\beta$``
    * **Display** (``mwe-math-element-block``) → ``$$S(\beta)=...$$``

    If the LaTeX source cannot be extracted the element is left
    untouched (the downstream converter will keep the ``<img>``).
    """
    for span in list(tree.xpath(
        f".//span[{cls_xpath('mwe-math-element')}]"
    )):
        parent = span.getparent()
        if parent is None:
            continue

        raw = extract_latex(span)
        if not raw:
            continue

        latex = strip_display_wrapper(raw)

        classes = (span.get("class") or "").split()
        if "mwe-math-element-block" in classes:
            replacement = f"$${latex}$$"
        else:
            replacement = f"${latex}$"

        # Replace the span with the LaTeX text node.
        tail = span.tail or ""
        prev = span.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + replacement + tail
        else:
            parent.text = (parent.text or "") + replacement + tail
        parent.remove(span)
