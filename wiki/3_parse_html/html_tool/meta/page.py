"""Page metadata extraction from HTML documents."""

from __future__ import annotations

import html as html_mod
import json
import re

from lxml.html import HtmlElement

from ..cleaner.page import cls_xpath, xpath_attr, xpath_first

FIELDS = ("title", "author", "date", "description", "url", "tags")

WIKI_URL_RE = re.compile(
    r"(wikipedia\.org|wikimedia\.org|mediawiki\.org|wiktionary\.org"
    r"|wikiquote\.org|wikisource\.org|wikibooks\.org|fandom\.com"
    r"|wiki\..*\.org)",
    re.IGNORECASE,
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
    ld_el = xpath_first(tree, ".//script[@type='application/ld+json']")
    if ld_el is not None and ld_el.text:
        try:
            ld = json.loads(ld_el.text)
            if isinstance(ld, list):
                ld = ld[0]
            if isinstance(ld, dict):
                if "name" in ld:
                    meta["title"] = ld["name"]
                if "headline" in ld:
                    meta["title"] = ld["headline"]
                if "datePublished" in ld:
                    meta["date"] = ld["datePublished"]
                author = ld.get("author")
                if isinstance(author, dict):
                    meta["author"] = author.get("name", "")
                elif isinstance(author, str):
                    meta["author"] = author
                if "description" in ld:
                    meta["description"] = ld["description"]
        except (json.JSONDecodeError, TypeError):
            pass

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
