"""Page metadata extraction from HTML documents."""

from __future__ import annotations

import html as html_mod
import json
import re
from typing import Any, Iterable

from lxml.html import HtmlElement

from ..cleaner.page import cls_xpath, xpath_attr, xpath_first

FIELDS = ("title", "author", "date", "description", "url", "tags")

WIKI_URL_RE = re.compile(
    r"(wikipedia\.org|wikimedia\.org|mediawiki\.org|wiktionary\.org"
    r"|wikiquote\.org|wikisource\.org|wikibooks\.org|fandom\.com"
    r"|wiki\..*\.org)",
    re.IGNORECASE,
)
JSON_LD_TYPES_BY_PRIORITY = (
    "NewsArticle",
    "Article",
    "BlogPosting",
    "WebPage",
)


class PageMeta:
    """Metadata extracted from an HTML page.

    All fields are optional; absent values are stored as empty strings.

    If an lxml *tree* is provided the constructor extracts metadata
    from it automatically.  Explicit keyword arguments override
    extracted values::

        meta = PageMeta(tree, url="https://…")
    """

    __slots__ = (
        "title", "author", "date", "description", "url", "tags",
        "remove_ref",
    )

    title: str
    author: str
    date: str
    description: str
    url: str
    tags: str
    remove_ref: bool

    def __init__(
        self,
        tree: HtmlElement,
        /,
        remove_ref: bool = False,
        **kwargs: str,
    ) -> None:
        """Extract metadata from *tree*; kwargs override."""
        self.remove_ref = remove_ref

        # Extract values from the DOM tree.
        extracted = extract_meta(tree)
        for f in FIELDS:
            setattr(self, f, extracted.get(f, ""))

        # Explicit kwargs override extracted / default values.
        for f in FIELDS:
            val = kwargs.get(f, "")
            if val:
                if f == "url":
                    val = html_mod.unescape(val)
                setattr(self, f, val)

    # -- predicates --------------------------------------------------------

    @property
    def is_wiki(self) -> bool:
        """Return ``True`` if the URL points to a wiki page."""
        return bool(self.url and WIKI_URL_RE.search(self.url))

    # -- dict-like helpers -------------------------------------------------

    def to_dict(self) -> dict[str, str]:
        """Return a dict of non-empty fields."""
        d = {f: getattr(self, f) for f in FIELDS if getattr(self, f)}
        if self.remove_ref:
            d["remove_ref"] = "true"
        return d

    def __repr__(self) -> str:
        """Return a developer-friendly representation."""
        pairs = ", ".join(f"{f}={getattr(self, f)!r}" for f in FIELDS)
        return f"PageMeta({pairs})"



# ---------------------------------------------------------------------------
# Standalone extraction function
# ---------------------------------------------------------------------------
def _iter_json_ld_items(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_ld_items(item)
        return
    if not isinstance(value, dict):
        return
    yield value
    graph = value.get("@graph")
    if graph is not None:
        yield from _iter_json_ld_items(graph)


def _json_ld_types(item: dict[str, Any]) -> set[str]:
    raw_type = item.get("@type")
    if isinstance(raw_type, str):
        return {raw_type}
    if isinstance(raw_type, list):
        return {str(value) for value in raw_type}
    return set()


def _json_ld_priority(item: dict[str, Any]) -> int:
    types = _json_ld_types(item)
    for index, type_name in enumerate(JSON_LD_TYPES_BY_PRIORITY):
        if type_name in types or any(item_type.endswith(f"/{type_name}") for item_type in types):
            return index
    return len(JSON_LD_TYPES_BY_PRIORITY) + 1


def _json_ld_text(value: Any, lookup: dict[str, dict[str, Any]]) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_json_ld_text(item, lookup) for item in value]
        return ", ".join(dict.fromkeys(part for part in parts if part))
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            return name.strip()
        ref = value.get("@id")
        if isinstance(ref, str) and ref in lookup and lookup[ref] is not value:
            return _json_ld_text(lookup[ref], lookup)
        identifier = value.get("url") or value.get("@id")
        if isinstance(identifier, str):
            return identifier.strip()
    return ""


def _extract_json_ld_meta(tree: HtmlElement) -> dict[str, str]:
    meta: dict[str, str] = {f: "" for f in FIELDS}
    scripts = tree.xpath(
        ".//script[contains(translate(@type,"
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
        "'application/ld+json')]"
    )

    items: list[dict[str, Any]] = []
    for script in scripts:
        raw_text = script.text or script.text_content() or ""
        if not raw_text.strip():
            continue
        try:
            items.extend(_iter_json_ld_items(json.loads(raw_text)))
        except (json.JSONDecodeError, TypeError):
            continue

    if not items:
        return meta

    lookup = {
        str(item["@id"]): item
        for item in items
        if isinstance(item.get("@id"), str)
    }
    candidates = [
        item
        for item in items
        if _json_ld_priority(item) <= len(JSON_LD_TYPES_BY_PRIORITY)
    ]
    if not candidates:
        return meta

    candidate = sorted(candidates, key=_json_ld_priority)[0]
    meta["title"] = _json_ld_text(candidate.get("headline"), lookup) or _json_ld_text(candidate.get("name"), lookup)
    meta["date"] = _json_ld_text(candidate.get("datePublished"), lookup) or _json_ld_text(candidate.get("dateModified"), lookup)
    meta["author"] = _json_ld_text(candidate.get("author"), lookup)
    meta["description"] = _json_ld_text(candidate.get("description"), lookup)
    meta["url"] = (
        _json_ld_text(candidate.get("url"), lookup)
        or _json_ld_text(candidate.get("mainEntityOfPage"), lookup)
    )
    meta["tags"] = _json_ld_text(candidate.get("articleSection") or candidate.get("keywords"), lookup)
    return meta


def extract_meta(tree: HtmlElement) -> dict[str, str]:
    """Extract metadata from an lxml HTML tree.

    Returns a dict with keys from :data:`FIELDS`.

    Sources tried (highest priority first):

    *Title* – ``<h1>``/``<h2>`` with content-class, then
    ``<title>`` tag (site-name suffix stripped).

    *Author / date / description* – JSON-LD
    ``<script type="application/ld+json">``, Open Graph
    ``<meta property="og:…">``, standard ``<meta name="…">``,
    ``<p class="author">``, and ``<time datetime="…">``.

    *URL* – ``<link rel="canonical">``, ``og:url``.

    *Tags* – delegated to
    :func:`dataclawdev.tool.html.meta.wiki.extract_wiki_meta`.
    """
    meta: dict[str, str] = {f: "" for f in FIELDS}

    # --- JSON-LD ----------------------------------------------------------
    meta.update({key: val for key, val in _extract_json_ld_meta(tree).items() if val})

    # --- Open Graph / standard meta tags ----------------------------------
    def _og(prop: str) -> str:
        return xpath_attr(tree, f".//meta[@property='{prop}']", "content")

    def _meta_name(name: str) -> str:
        return xpath_attr(tree, f".//meta[@name='{name}']", "content")

    if not meta["title"]:
        meta["title"] = _og("og:title")
    if not meta["description"]:
        meta["description"] = (
            _og("og:description")
            or _meta_name("description")
        )
    if not meta["author"]:
        meta["author"] = _meta_name("author")
    if not meta["date"]:
        meta["date"] = _meta_name("date")

    if not meta["url"]:
        canon = xpath_attr(tree, ".//link[@rel='canonical']", "href")
        raw_url = canon or _og("og:url")
        meta["url"] = html_mod.unescape(raw_url) if raw_url else ""

    # --- Heading-based title (most precise, overrides if found) -----------
    for heading_tag in ("h1", "h2"):
        for cls_name in (
            "entry-title", "post-title", "topic-title",
            "article-title", "page-title",
        ):
            hit = xpath_first(tree, f".//{heading_tag}[{cls_xpath(cls_name)}]")
            if hit is not None:
                meta["title"] = (hit.text_content() or "").strip()
                break
        if meta["title"]:
            break

    # --- <title> fallback -------------------------------------------------
    if not meta["title"]:
        title_el = xpath_first(tree, ".//title")
        if title_el is not None:
            text = (title_el.text_content() or "").strip()
            text = re.split(
                r"\s*[|\u2013\u2014\u2015\u2212\u2013\u2014\u2013\u2014\u2013\u2014–—-]\s+",
                text, maxsplit=1,
            )[0]
            meta["title"] = text.strip()

    # --- <time datetime="…"> for date -------------------------------------
    if not meta["date"]:
        time_el = xpath_first(tree, ".//time[@datetime]")
        if time_el is not None:
            meta["date"] = time_el.get("datetime", "")

    # --- <p class="author"> / <span class="author"> for author ------------
    if not meta["author"]:
        for tag_name in ("p", "span", "div"):
            author_el = xpath_first(
                tree, f".//{tag_name}[{cls_xpath('author')}]"
            )
            if author_el is not None:
                username = xpath_first(
                    author_el, f".//*[{cls_xpath('username')}]"
                )
                if username is not None:
                    meta["author"] = (username.text_content() or "").strip()
                else:
                    meta["author"] = (author_el.text_content() or "").strip()
                break

    # --- Wiki-specific fields (tags, etc.) --------------------------------
    from .wiki import extract_wiki_meta

    wiki_meta = extract_wiki_meta(tree)
    for key, val in wiki_meta.items():
        if val and not meta.get(key):
            meta[key] = val

    return meta
