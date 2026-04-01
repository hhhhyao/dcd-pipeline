"""Simple-HTML converter – output body content with attributes stripped.

:class:`HtmlConverter` serialises the cleaned DOM tree to a minimal
HTML fragment keeping only the body content.  All ``class``, ``id``,
``style``, and other non-essential attributes are removed so the
output contains pure structural HTML.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lxml.html import HtmlElement, tostring

from ..cleaner.page import resolve_relative_urls

if TYPE_CHECKING:
    from ..meta import PageMeta

# Tags allowed in simplified HTML output – everything else is unwrapped.
ALLOWED_TAGS: frozenset[str] = frozenset(
    [
        # Headings
        "h1", "h2", "h3", "h4", "h5", "h6",
        # Block-level text
        "p", "blockquote", "pre", "hr",
        # Inline formatting
        "strong", "b", "em", "i", "u", "s", "del", "ins",
        "code", "mark", "sub", "sup", "br",
        # Lists
        "ul", "ol", "li",
        # Tables
        "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
        # Media
        "img", "figure", "figcaption",
        "audio", "video", "source",
        # Links
        "a",
    ]
)

# Attributes to keep – everything else is stripped.
KEEP_ATTRS = frozenset(
    [
        "href", "src", "alt", "srcset", "colspan", "rowspan",
        "poster", "controls", "type",
    ]
)

# Void (self-closing) tags that should never be removed.
VOID_TAGS = frozenset(
    ["img", "br", "hr", "input", "meta", "link", "source"]
)


class HtmlConverter:
    """Converter that outputs a clean HTML body fragment.

    All CSS-related attributes (``class``, ``id``, ``style``, ``data-*``,
    etc.) are stripped.  Only essential content attributes (``href``,
    ``src``, ``alt``, …) are preserved.

    Usage::

        converter = HtmlConverter(meta)
        html = converter.convert(content_tree)
    """

    def __init__(self, meta: PageMeta) -> None:
        """Initialise with page metadata."""
        self._meta = meta

    def convert(self, tree: HtmlElement) -> str:
        """Strip non-content tags and attributes, then serialise."""
        resolve_relative_urls(tree, self._meta.url)
        strip_non_content_tags(tree)
        strip_attrs(tree)
        remove_empty_elements(tree)
        return inner_html(tree)



def strip_non_content_tags(tree: HtmlElement) -> None:
    """Keep only basic formatting tags and strip everything else.

    Operates **in-place** on *tree*.  Any element whose tag is **not**
    in :data:`ALLOWED_TAGS` is *unwrapped* – its children and text
    are preserved but the element itself is removed.
    """
    from ..cleaner.page import unwrap

    # We must iterate bottom-up so that unwrapping a parent doesn't
    # displace children we haven't visited yet.
    for el in reversed(list(tree.iter())):
        if not isinstance(el.tag, str):
            continue
        if el.tag in ALLOWED_TAGS:
            continue
        # Never unwrap the root element or structural wrappers.
        if el is tree or el.tag in ("html", "body", "head"):
            continue
        unwrap(el)


def inner_html(el: HtmlElement) -> str:
    """Return inner HTML of *el* (without the outer tag)."""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(tostring(child, encoding="unicode", method="html"))
    return "".join(parts)


def remove_empty_elements(tree: HtmlElement) -> None:
    """Remove elements that have no text content and no children.

    Self-closing tags like ``<img>`` and ``<br>`` are kept.
    """
    from ..cleaner.page import remove_element

    for el in reversed(list(tree.iter())):
        if not isinstance(el.tag, str):
            continue
        if el is tree:
            continue
        if el.tag in VOID_TAGS:
            continue
        if len(el) == 0 and not (el.text and el.text.strip()):
            remove_element(el)


def strip_attrs(tree: HtmlElement) -> None:
    """Remove all attributes except those in :data:`KEEP_ATTRS`.

    The ``class`` attribute is preserved on ``<code>`` elements when
    it specifies a language (e.g. ``language-python``).
    """
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue
        to_remove = [a for a in el.attrib if a not in KEEP_ATTRS]
        for a in to_remove:
            if (
                a == "class"
                and el.tag == "code"
                and (el.get("class") or "").startswith("language-")
            ):
                continue
            del el.attrib[a]


def make_html_converter(meta: PageMeta) -> HtmlConverter:
    """Return an :class:`HtmlConverter` instance."""
    return HtmlConverter(meta)
