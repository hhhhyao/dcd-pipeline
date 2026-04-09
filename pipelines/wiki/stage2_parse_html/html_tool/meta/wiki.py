"""Wiki-specific metadata extraction from MediaWiki HTML pages."""

from __future__ import annotations

import re

from lxml.html import HtmlElement

_STUB_CAT_RE = re.compile(
    r"stubs?$|小作品$|スタブ$",
    re.IGNORECASE,
)


def _is_stub_category(name: str) -> bool:
    """Return True if *name* is a Wikipedia stub category."""
    return bool(_STUB_CAT_RE.search(name))


def extract_wiki_meta(tree: HtmlElement) -> dict[str, str]:
    """Extract wiki-specific metadata from *tree*.

    Currently extracts:

    *Categories* -- visible article categories from the
    ``<div id="mw-normal-catlinks">`` block.  Hidden/maintenance
    categories (``mw-hidden-catlinks``) are ignored.  Stub
    categories (e.g. "2020s film stubs") are also filtered out.

    Returns a dict with wiki-specific keys (e.g. ``"tags"``).
    Values are empty strings when the field is not found.
    """
    meta: dict[str, str] = {}

    # --- Categories -------------------------------------------------------
    cat_links: list[HtmlElement] = tree.xpath(
        ".//div[@id='mw-normal-catlinks']//ul/li/a"
    )
    if cat_links:
        cats = [
            (a.text_content() or "").strip()
            for a in cat_links
        ]
        cats = [c for c in cats if c and not _is_stub_category(c)]
        meta["tags"] = ", ".join(cats)

    return meta
