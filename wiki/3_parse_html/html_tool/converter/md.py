"""Markdown converter – thin wrapper around html-to-markdown."""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from lxml.html import HtmlElement, tostring

__version__ = "0.1.0"
from ..cleaner.page import (
    replace_audio_elements,
    replace_video_elements,
    resolve_relative_urls,
    unwrap,
)

if TYPE_CHECKING:
    from ..meta import PageMeta


def unwrap_sup_sub(tree: HtmlElement) -> None:
    """Unwrap ``<sup>`` and ``<sub>`` tags, preserving their text.

    The ``html-to-markdown`` library silently drops all ``<sup>``/
    ``<sub>`` content.  Unwrapping them keeps the text inline so
    that citation markers like ``[36]`` and subscripts survive the
    Markdown conversion.
    """
    for tag_name in ("sup", "sub"):
        for el in list(tree.iter(tag_name)):
            if el.getparent() is not None:
                unwrap(el)


def remove_void_list_items(tree: HtmlElement) -> None:
    """Remove ``<li>`` elements that have no text content.

    lxml serialises empty ``<li>`` elements as self-closing tags
    (``<li>``), which html-to-markdown mis-parses — it absorbs all
    subsequent siblings into the unclosed list item, causing silent
    content loss.  Stripping them before serialisation prevents this.
    """
    for li in list(tree.iter("li")):
        if li.getparent() is None:
            continue
        text = (li.text_content() or "").strip()
        if not text and not li.xpath(".//img"):
            li.getparent().remove(li)


def flatten_nested_tables(tree: HtmlElement) -> None:
    """Extract tables nested inside table cells.

    Markdown has no nested-table support.  Any ``<table>`` found
    inside a ``<td>`` or ``<th>`` of another table is pulled out and
    placed immediately after the outermost ancestor table, so both
    the outer and inner tables render as proper markdown tables.

    Processes bottom-up: innermost nested tables are extracted first,
    so multi-level nesting is handled by repeated passes.
    """
    while True:
        candidates = []
        for table in tree.xpath(".//table"):
            cell = table.getparent()
            if cell is None or cell.tag not in ("td", "th"):
                continue
            if not table.xpath(".//td/table | .//th/table"):
                candidates.append(table)
        if not candidates:
            break
        for table in candidates:
            extract_nested_table(table)


def find_outermost_table(el: HtmlElement) -> HtmlElement | None:
    """Walk up from *el* to find the outermost ``<table>`` ancestor."""
    outermost = None
    parent = el.getparent()
    while parent is not None:
        if parent.tag == "table":
            outermost = parent
        parent = parent.getparent()
    return outermost


def extract_nested_table(table: HtmlElement) -> None:
    """Move *table* out of its cell, placing it after the outer table."""
    outer = find_outermost_table(table)
    if outer is None:
        return
    outer_parent = outer.getparent()
    if outer_parent is None:
        return

    cell = table.getparent()
    if cell is None:
        return

    # Detach the nested table from its cell.
    table.tail = None
    cell.remove(table)

    # Insert after the outermost table.
    idx = list(outer_parent).index(outer)
    outer_parent.insert(idx + 1, table)


class MarkdownConverter:
    """Thin wrapper around the ``html-to-markdown`` library.

    Resolves the underlying conversion callable once on first use and
    caches it for subsequent calls.

    Usage::

        converter = MarkdownConverter(meta)
        md = converter.convert(cleaned_html)
    """

    def __init__(self, meta: PageMeta) -> None:
        """Initialise with page metadata."""
        self._fn: Callable[..., str] | None = None
        self._opts: object | None = None
        self._meta = meta

    def _resolve(self) -> Callable[..., str]:
        """Load html-to-markdown and return the conversion callable."""
        try:
            module = importlib.import_module("html_to_markdown")
        except Exception:
            print(
                "Missing dependency: pip install html-to-markdown",
                file=sys.stderr,
            )
            sys.exit(1)

        if hasattr(module, "ConversionOptions"):
            opts_cls = module.ConversionOptions
            self._opts = opts_cls(
                code_block_style="backticks",
            )

        if hasattr(module, "convert"):
            return cast(Callable[..., str], module.convert)
        if hasattr(module, "html_to_markdown"):
            return cast(Callable[..., str], module.html_to_markdown)

        print("Unsupported html-to-markdown export shape.", file=sys.stderr)
        sys.exit(1)

    def convert(self, tree: HtmlElement) -> str:
        """Convert an HTML DOM tree to Markdown.

        Serialises *tree* to an HTML string internally before passing
        it to the ``html-to-markdown`` library.  If *meta* was provided
        to the constructor, YAML front matter is prepended.
        """
        if self._fn is None:
            self._fn = self._resolve()
        unwrap_sup_sub(tree)
        replace_video_elements(tree)
        replace_audio_elements(tree)
        resolve_relative_urls(tree, self._meta.url)
        flatten_nested_tables(tree)
        remove_void_list_items(tree)
        html = tostring(tree, encoding="unicode", method="html")
        if self._opts is not None:
            markdown = self._fn(html, options=self._opts)
        else:
            markdown = self._fn(html)
        markdown = normalize_whitespace(markdown)
        front_matter = format_front_matter(self._meta.to_dict())
        if front_matter:
            markdown = front_matter + markdown
        return markdown


BLANK_ONLY_WS_RE = re.compile(r"^[\s]+$", re.MULTILINE)
EXCESS_BLANKS_RE = re.compile(r"\n{3,}")
HTML_ENTITY_RE = re.compile(r"&amp;|&lt;|&gt;|&quot;|&#39;")
TRAILING_EMPTY_CELLS_RE = re.compile(r"(\s*\|)+\s*$")
BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


_ENTITY_MAP = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
}


def normalize_whitespace(text: str) -> str:
    """Clean up whitespace and leftover HTML entities in markdown output."""
    text = BLANK_ONLY_WS_RE.sub("", text)
    text = EXCESS_BLANKS_RE.sub("\n\n", text)
    text = HTML_ENTITY_RE.sub(lambda m: _ENTITY_MAP[m.group(0)], text)
    text = BR_TAG_RE.sub("", text)
    text = _strip_trailing_empty_cells(text)
    return text.lstrip("\n")


def _strip_trailing_empty_cells(text: str) -> str:
    """Strip trailing empty columns from markdown tables.

    Groups consecutive table lines (lines starting with ``|``) into
    tables and removes trailing columns that are empty in every row.
    Also removes rows that consist entirely of empty cells and splits
    collapsed sub-tables (rows with embedded ``| --- |`` separators)
    into proper multi-row tables.
    """
    lines = text.split("\n")
    out: list[str] = []
    table_buf: list[str] = []

    def _flush_table() -> None:
        if not table_buf:
            return
        expanded: list[str] = []
        for line in table_buf:
            if "| --- |" in line and line.count("| --- |") >= 1:
                result = _expand_collapsed_table(line)
                if result:
                    expanded.extend(result)
                    continue
            expanded.append(line)

        # Drop all-empty rows
        cleaned: list[str] = []
        for line in expanded:
            stripped = TRAILING_EMPTY_CELLS_RE.sub("", line)
            if stripped.strip() == "|" or not stripped.strip():
                continue
            cleaned.append(line)

        if not cleaned:
            table_buf.clear()
            return

        # Count cells per row to find the max content column index
        def _cell_count(row: str) -> int:
            inner = row.strip().strip("|")
            return len(inner.split("|")) if inner.strip() else 0

        def _cell_has_content(row: str, col: int) -> bool:
            inner = row.strip().strip("|")
            parts = inner.split("|")
            if col >= len(parts):
                return False
            cell = parts[col].strip()
            return bool(cell) and cell != "---"

        max_cols = max((_cell_count(r) for r in cleaned), default=0)
        if max_cols < 2:
            out.extend(cleaned)
            table_buf.clear()
            return

        # Find rightmost column with content in any row
        keep = 1
        for col in range(max_cols):
            for row in cleaned:
                if _cell_has_content(row, col):
                    keep = col + 1
                    break

        trimmed: list[str] = []
        for line in cleaned:
            inner = line.strip().strip("|")
            parts = inner.split("|")
            kept = parts[:keep]
            row_str = "| " + " | ".join(c.strip() for c in kept) + " |"
            trimmed.append(row_str)

        if trimmed and _is_separator(trimmed[0]):
            header = "| " + " | ".join("" for _ in range(keep)) + " |"
            trimmed.insert(0, header)

        out.extend(trimmed)
        table_buf.clear()

    for line in lines:
        if line.lstrip().startswith("|"):
            table_buf.append(line)
        else:
            _flush_table()
            out.append(line)
    _flush_table()

    return "\n".join(out)


_SEP_PATTERN = re.compile(r"\|\s*---\s*\|")
_SEP_ROW_RE = re.compile(r"^\|\s*(:?-+:?\s*\|\s*)+$")


def _is_separator(row: str) -> bool:
    """Return *True* if *row* is a markdown table separator row."""
    return bool(_SEP_ROW_RE.match(row.strip()))


def _expand_collapsed_table(line: str) -> list[str] | None:
    """Split a single markdown line that contains an embedded table.

    Returns a list of properly formatted table rows, or None if the
    line doesn't actually contain a collapsed table.
    """
    sep_match = _SEP_PATTERN.search(line)
    if not sep_match:
        return None

    header = line[: sep_match.start()].rstrip()
    rest = line[sep_match.end() :].lstrip()

    if not header.strip().startswith("|"):
        return None

    header_cells = [
        c.strip() for c in header.strip().strip("|").split("|")
    ]
    n_cols = len(header_cells)
    if n_cols < 1:
        return None

    sep_row = "| " + " | ".join("---" for _ in range(n_cols)) + " |"
    header_row = "| " + " | ".join(header_cells) + " |"

    rows = [header_row, sep_row]

    remaining_cells = [c.strip() for c in rest.strip("|").split("|") if True]
    remaining_cells = [c.strip() for c in rest.strip().strip("|").split("|")]

    for i in range(0, len(remaining_cells), n_cols):
        chunk = remaining_cells[i : i + n_cols]
        while len(chunk) < n_cols:
            chunk.append("")
        non_empty = [c for c in chunk if c.strip()]
        if not non_empty:
            continue
        row_str = "| " + " | ".join(chunk) + " |"
        rows.append(row_str)

    return rows


def format_front_matter(meta: dict[str, str]) -> str:
    """Format metadata as YAML front matter."""
    if not meta:
        return ""
    lines = ["---"]
    for key in (
        "title", "author", "date", "description",
        "url", "tags", "remove_ref",
    ):
        if key not in meta:
            continue
        val = meta[key]
        if key == "tags" and val:
            lines.append("tags:")
            for cat in val.split(", "):
                cat = cat.strip()
                if cat:
                    lines.append(f"  - {cat}")
            continue
        needs_quote = (
            any(c in val for c in ":#{}[]|>&*!")
            or val.startswith(("'", '"'))
        )
        if needs_quote:
            val = f'"{val}"'
        lines.append(f"{key}: {val}")
    lines.append("code_source: \"https://github.com/agi-otw/adp\"")
    lines.append(f"version: {__version__}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def make_md_converter(meta: PageMeta) -> MarkdownConverter:
    """Return the appropriate converter based on page metadata.

    Inspects ``meta["url"]`` (and potentially other fields) to detect
    wiki pages and returns a :class:`WikiMDConverter` for those.
    Falls back to the base :class:`MarkdownConverter` otherwise.
    """
    if meta and hasattr(meta, "is_wiki") and meta.is_wiki:
        from .wiki import WikiMDConverter
        return WikiMDConverter(meta)
    return MarkdownConverter(meta)
