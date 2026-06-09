"""HTML page cleaner – extract main content and metadata.

Parses an HTML document into a DOM tree with lxml, identifies the main
content container via tiered XPath expressions, strips boilerplate
(ads, navigation, comments, scripts, social links, …), and returns
the cleaned content subtree.

Typical usage::

    cleaner = make_cleaner(meta)
    meta, content = cleaner.clean(tree)
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from lxml import etree
from lxml.html import HtmlElement

if TYPE_CHECKING:
    from ..meta import PageMeta

# ---------------------------------------------------------------------------
# XPath helpers
# ---------------------------------------------------------------------------

def cls_xpath(name: str) -> str:
    """Return an XPath predicate that matches a CSS class name."""
    return f"contains(concat(' ',normalize-space(@class),' '),' {name} ')"


# ---------------------------------------------------------------------------
# Keyword patterns – used to match class / id attribute values
# ---------------------------------------------------------------------------
AD_KEYWORDS = re.compile(
    r"(?<![a-z0-9\-])"
    r"(ad|ads|advert|banner|cookie|consent|copyright|disclaimer|newsletter|promo|sidebar|subscribe|"
    r"sponsor|breadcrumb|sponsored|marketing)"
    r"(?![a-z0-9\-])",
    re.IGNORECASE,
)
SUBSCRIBE_KEYWORDS = re.compile(
    r"(?<![a-z0-9\-])"
    r"(subscribe|subscription|newsletter)"
    r"(?![a-z0-9\-])",
    re.IGNORECASE,
)
COMMENT_KEYWORDS = re.compile(
    r"(?<![a-z0-9\-])"
    r"(comment|comments|commentform|comment-form|comment-respond|reply|"
    r"respond)"
    r"(?![a-z0-9\-])",
    re.IGNORECASE,
)
FORUM_UI_KEYWORDS = re.compile(
    r"(?<![a-z0-9\-])"
    r"(headerbar|navbar|navbox|quick-links|breadcrumbs|search-box|action-bar|"
    r"pagination|postprofile|actions-jump|jumpbox|nav-breadcrumbs|"
    r"linklist|navlinks|topic-actions|post-buttons|rightside|"
    r"dropdown-contents|hatnote|headerlink|navigation|toolbar|"
    r"external-links|catlinks|trust-badge|"
    r"printfooter)"
    r"(?![a-z0-9\-])",
    re.IGNORECASE,
)

KEYWORD_PATTERNS = (
    AD_KEYWORDS,
    SUBSCRIBE_KEYWORDS,
    COMMENT_KEYWORDS,
    FORUM_UI_KEYWORDS,
)

# CSS-module class names (e.g. "toolbar-module__container__abc123") put the
# keyword *before* a hyphen, which the word-boundary lookahead above rejects.
# This pattern catches them.
CSS_MODULE_NOISE_RE = re.compile(
    r"^(toolbar|sidebar|banner|cookie|consent|subscribe|newsletter|"
    r"ad|ads|advert|navigation|navbar|comment|sign-off)-module(?![a-z0-9\-])",
    re.IGNORECASE,
)

# Noise words matched against tokenised data-testid values.  Tokens are
# obtained by splitting on hyphens, underscores, and camelCase boundaries.
TESTID_NOISE_WORDS = frozenset({
    "ad", "ads", "advert", "banner", "cookie", "consent", "copyright",
    "disclaimer", "newsletter", "promo", "sidebar", "subscribe",
    "sponsor", "toolbar", "navbar", "navigation", "comment",
    "pagination", "licence", "license",
})
CAMEL_SPLIT_RE = re.compile(r"[A-Z][a-z]*|[a-z]+|[0-9]+")

# Chinese editorial chrome: 【纠错】 (error correction button).
CN_EDITORIAL_RE = re.compile(r"^\s*【纠错】\s*$")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOCIAL_DOMAINS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "youtube.com",
    "t.me",
    "pinterest.com",
    "reddit.com",
    "threads.net",
    "mastodon.social",
    "bsky.app",
)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")

HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

# Tags removed early (before content-area identification) because they
# never carry article text and would skew text-length calculations.
EARLY_STRIP_TAGS = {"script", "style", "noscript"}

# Tags whose entire subtree should be dropped during noise removal
# (after the content area has been identified).
STRIP_TAGS = frozenset(
    [
        "iframe",
        "ins",  # ad containers
        "svg",  # inline icons
        "nav",
        "footer",
        "aside",  # layout boilerplate
    ]
)

# Data-attribute names that signal ad or responsive-menu elements
AD_DATA_ATTRS = frozenset(
    ["data-ad", "data-ads", "data-advertisement"]
)
# Attribute name→value pairs that indicate affiliate / ad content.
AD_DATA_VALUES = {
    "data-img": "affiliate",
}
RESPONSIVE_DATA_ATTRS = frozenset(
    ["data-last-responsive", "data-skip-responsive"]
)

# Regex matching class values that mark a forum post container.
POST_CLASS_RE = re.compile(
    r"(?<![a-z0-9])(post|message|postbody)(?![a-z0-9])",
    re.IGNORECASE,
)

INLINE_TAGS = frozenset({
    "sup", "sub", "span", "em", "strong", "b", "i", "u",
    "code", "small", "mark", "abbr", "cite",
})

NAV_LINK_PREFIXES = (
    # English
    "jump to", "skip to", "go to", "scroll to",
    # Chinese (simplified + traditional)
    "跳转到", "跳轉到", "跳到", "跳至",
    "前往", "转到", "轉到",
)
NAV_LINK_EXACT = {
    "top", "back to top",
    "顶部", "頂部", "回到顶部", "回到頂部",
    "返回顶部", "返回頂部",
}

URL_ATTRS = {"src", "href", "srcset"}

# ---------------------------------------------------------------------------
# Content-area identification – tiered XPath expressions
# ---------------------------------------------------------------------------
# Tried in order from most specific to broadest.  The first match whose
# subtree passes validation (enough visible text) is selected as the
# content root.  When nothing matches we fall back to <body> or the
# full document.
CONTENT_XPATH: list[list[str]] = [
    # Tier 1 – precise semantic article markup
    # Schema.org structured data, WordPress (.entry-content,
    # .post-content), Ghost, Hugo, Jekyll, news/magazine CMSes
    # (.article-body, .article-content), Blogger/Blogspot
    # (.post-body), Tumblr, Discourse, vBulletin (.post-text).
    [
        ".//*[@itemprop='articleBody']",              # Schema.org
        f".//*[{cls_xpath('post-content')}]",  # WordPress, Ghost, Hugo
        f".//*[{cls_xpath('post_content')}]",
        f".//*[{cls_xpath('postcontent')}]",
        f".//*[{cls_xpath('postContent')}]",
        f".//*[{cls_xpath('article-content')}]",  # News sites, BEM
        f".//*[{cls_xpath('article__content')}]",
        f".//*[{cls_xpath('article-body')}]",  # Reuters, Bloomberg
        f".//*[{cls_xpath('article__body')}]",
        f".//*[{cls_xpath('entry-content')}]",  # WordPress core
        ".//*[@id='entry-content']",
        ".//*[@id='article-content']",  # Custom news templates
        ".//*[@id='article-body']",
        f".//*[{cls_xpath('post-text')}]",  # vBulletin, Discourse
        f".//*[{cls_xpath('post_text')}]",
        f".//*[{cls_xpath('post-body')}]",  # Blogger, Tumblr
        f".//*[{cls_xpath('post-entry')}]",  # Older WP, Movable Type
        f".//*[{cls_xpath('postentry')}]",
    ],
    # Tier 2 – <article> element
    [".//article"],
    # Tier 3 – broader layout conventions
    # CMS story/blog wrappers, WPBakery page builder, MediaWiki.
    [
        f".//*[{cls_xpath('storycontent')}]",   # Joomla
        f".//*[{cls_xpath('story-content')}]",  # NYT, AP News
        f".//*[{cls_xpath('story-body')}]",     # Reuters, BBC
        f".//*[{cls_xpath('blog-content')}]",   # Blog platforms
        f".//*[{cls_xpath('section-content')}]",  # Squarespace
        f".//*[{cls_xpath('single-content')}]",  # WP single-post
        f".//*[{cls_xpath('theme-content')}]",  # ThemeForest
        f".//*[{cls_xpath('page-content')}]",   # Wix, SSGs
        f".//*[{cls_xpath('text-content')}]",   # Medium, Substack
        f".//*[{cls_xpath('body-text')}]",      # Guardian, Atlantic
        f".//*[{cls_xpath('body-content')}]",   # Legacy CMS
        ".//*[@id='story']",                    # NYT, WaPo
        f".//*[{cls_xpath('story')}]",          # News sites
        f".//*[{cls_xpath('field-body')}]",     # Drupal
        ".//*[@role='article']",                # ARIA
        f".//*[{cls_xpath('wpb_text_column')}]",  # WPBakery
        f".//*[{cls_xpath('mw-body-content')}]",  # MediaWiki
        ".//*[@id='bodyContent']",              # MediaWiki old
        ".//*[@id='detail']",                    # Xinhua, CN news detail
        f".//*[{cls_xpath('rm_txt_con')}]",       # People's Daily
    ],
    # Tier 4 – generic "content" / "main-content" containers
    # Broad catch-all for sites that wrap their main area in a
    # container named "content" or "main-content".
    [
        f".//*[{cls_xpath('content-main')}]",  # Bootstrap
        f".//*[{cls_xpath('content_main')}]",  # Django, Rails
        f".//*[{cls_xpath('main-content')}]",  # Shopify
        f".//*[{cls_xpath('content-body')}]",  # Confluence
        f".//*[{cls_xpath('content__body')}]",  # BEM
        ".//*[@id='content-main']",            # Custom CMS
        ".//*[@id='content-body']",            # Confluence
        ".//*[@id='contentBody']",             # camelCase
        ".//*[@id='content']",                 # Generic id
        ".//*[@id='Content']",                 # Generic id (capitalized)
        f".//*[{cls_xpath('content')}]",       # Catch-all
    ],
    # Tier 5 – <main> or role="main"
    # HTML5 landmark element, used as the last resort before
    # falling back to <body>.
    [
        ".//main",
        ".//*[@role='main']",
    ],
]

# Minimum visible-text length (in characters) for a candidate content
# area to be accepted.  Prevents tiny fragments from being chosen.
MIN_CONTENT_LENGTH = 50


# ---------------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------------
def el_classes(el: HtmlElement) -> list[str]:
    """Return the list of CSS classes on *el*."""
    raw = el.get("class", "")
    return raw.split() if raw else []


def matches_keyword(el: HtmlElement) -> bool:
    """Check if class, id, or data-testid contains a boilerplate keyword."""
    classes = el_classes(el)
    el_id = el.get("id", "")

    for pattern in KEYWORD_PATTERNS:
        for cls in classes:
            if pattern.search(cls):
                return True
        if el_id and pattern.search(el_id):
            return True

    # CSS-module class names: "toolbar-module__container__hash"
    for cls in classes:
        if CSS_MODULE_NOISE_RE.search(cls):
            return True

    # data-testid tokens: split "promo-box" / "ArticleToolbar" into words
    testid = el.get("data-testid") or ""
    if testid:
        tokens = {t.lower() for t in CAMEL_SPLIT_RE.findall(testid)}
        if tokens & TESTID_NOISE_WORDS:
            return True

    return False


def has_ad_data_attr(el: HtmlElement) -> bool:
    """Return True if the element carries an ad-related data attribute."""
    if AD_DATA_ATTRS & set(el.attrib):
        return True
    return any(
        el.get(attr) == val for attr, val in AD_DATA_VALUES.items()
    )


def has_responsive_data_attr(el: HtmlElement) -> bool:
    """Return True if the element carries a responsive-menu data attribute."""
    return bool(RESPONSIVE_DATA_ATTRS & set(el.attrib))


def is_visually_hidden(el: HtmlElement) -> bool:
    """Return True if the element uses the common visually-hidden CSS pattern.

    Many sites hide screen-reader-only text with a combination of
    ``clip: rect(0 0 0 0)``, ``position: absolute``, and ``height: 1px``.
    This text (e.g. ", opens new tab", "category") produces junk when
    converted to Markdown.
    """
    style = el.get("style") or ""
    return "clip:rect(0" in style or "clip: rect(0" in style


def is_social_link(el: HtmlElement) -> bool:
    """Return True if an <a> element links to a social-media domain."""
    href = el.get("href", "")
    if not href:
        return False
    return any(d in href for d in SOCIAL_DOMAINS)


def is_print_link(el: HtmlElement) -> bool:
    """Return True if an <a> element is a print button or link."""
    href = (el.get("href") or "").lower()
    title = (el.get("title") or "").lower()
    return "print" in href or "print" in title


def is_nav_fragment_link(el: HtmlElement) -> bool:
    """Return True if a fragment ``<a>`` should be removed entirely.

    Matches two heuristics:

    1. **Text-pattern** -- the visible text matches a known skip/jump
       navigation phrase (e.g. "Jump to Recipe", "Skip to content").
    2. **Structural** -- the link is the only meaningful content inside
       its parent block element (standalone nav link).

    Links that are inline within running prose are left alone so that
    ``unwrap_links`` can preserve their text.
    """
    href = el.get("href", "")
    if not href.startswith("#"):
        return False

    text = (el.text_content() or "").strip().lower()
    if not text:
        return False

    # Heuristic 1: known navigation phrases
    if text in NAV_LINK_EXACT:
        return True
    if any(text.startswith(p) for p in NAV_LINK_PREFIXES):
        return True

    # Heuristic 2: standalone fragment link (sole child of a *block*
    # parent).  Inline wrappers like ``<sup class="reference">`` are
    # excluded so that citation back-links survive.
    parent = el.getparent()
    if parent is not None and parent.tag not in INLINE_TAGS:
        siblings = [c for c in parent if c is not el]
        parent_text = (parent.text or "").strip()
        el_tail = (el.tail or "").strip()
        if not siblings and not parent_text and not el_tail:
            return True

    return False


def is_image_href(href: str) -> bool:
    """Return True if *href* points to an image file."""
    return href.lower().split("?")[0].endswith(IMAGE_EXTS)


def remove_element(el: HtmlElement) -> None:
    """Remove *el* from the tree, preserving its tail text."""
    parent = el.getparent()
    if parent is None:
        return
    # Preserve tail text (text after this element's closing tag).
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def unwrap(el: HtmlElement) -> None:
    """Remove the element but keep its children and text in place.

    Equivalent to BeautifulSoup's ``tag.unwrap()``.  Handles lxml's
    text/tail model: element text goes before the first child, tail
    text of the removed element goes after the last child (or is
    appended to the parent/previous sibling text).
    """
    parent = el.getparent()
    if parent is None:
        return
    idx = list(parent).index(el)
    children = list(el)

    # 1. Merge el.text into the tree before el's position.
    if el.text:
        if idx > 0:
            prev = parent[idx - 1]
            prev.tail = (prev.tail or "") + el.text
        else:
            parent.text = (parent.text or "") + el.text

    # 2. Move children into parent at el's position.
    for i, child in enumerate(children):
        parent.insert(idx + i, child)

    # 3. Merge el.tail onto the last moved child, or back into
    #    the text stream before el's position.
    if el.tail:
        if children:
            last_child = children[-1]
            last_child.tail = (last_child.tail or "") + el.tail
        elif idx > 0:
            prev = parent[idx - 1] if not children else children[-1]
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail

    parent.remove(el)


def should_remove(
    el: HtmlElement,
    *,
    skip_social: bool = False,
) -> bool:
    """Decide whether *el* (and its subtree) should be stripped.

    Parameters
    ----------
    skip_social:
        When *True*, social-media links are kept (useful for wiki pages
        where "External links" sections contain legitimate content).
    """
    tag = el.tag
    if not isinstance(tag, str):
        return False

    # Unwanted tag types
    if tag in STRIP_TAGS:
        return True

    # Boilerplate class / id
    if matches_keyword(el):
        return True

    # Ad-related or responsive-menu data attributes
    if has_ad_data_attr(el) or has_responsive_data_attr(el):
        return True

    # Banner / note role
    if el.get("role") in ("banner", "note"):
        return True

    # Visually-hidden / screen-reader-only elements (e.g. ", opens new tab")
    if is_visually_hidden(el):
        return True

    # Links that should be removed entirely (social, print, nav fragment)
    if tag == "a":
        if not skip_social and is_social_link(el):
            return True
        if is_print_link(el) or is_nav_fragment_link(el):
            return True

    return False


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------
def xpath_first(tree: HtmlElement, expr: str) -> HtmlElement | None:
    """Return the first element matching *expr*, or None."""
    results = tree.xpath(expr)
    for r in results:
        if isinstance(r, HtmlElement):
            return r
    return None


def xpath_attr(tree: HtmlElement, expr: str, attr: str) -> str:
    """Return the *attr* value of the first element matching *expr*."""
    el = xpath_first(tree, expr)
    if el is not None:
        return el.get(attr, "") or ""
    return ""


# ---------------------------------------------------------------------------
# Content-cleaning passes (module-level)
# ---------------------------------------------------------------------------
EMPTY_TIME_RE = re.compile(r"^\s*(ago)?\s*$")
EMPTY_RELATIVE_TIME_RE = re.compile(
    r"^\s*(updated\s+)?ago\s*$", re.IGNORECASE,
)


def remove_noise(
    content: HtmlElement,
    *,
    skip_social: bool = False,
) -> None:
    """Remove unwanted elements (ads, nav chrome, social links, …)."""
    to_remove = [
        el for el in content.iter()
        if isinstance(el, HtmlElement)
        and should_remove(el, skip_social=skip_social)
    ]
    for el in to_remove:
        if el.getparent() is not None:
            remove_element(el)

    # Strip <time> elements whose visible text is just "ago" (JS placeholder).
    for el in list(content.iter("time")):
        text = (el.text_content() or "").strip()
        if EMPTY_TIME_RE.match(text):
            remove_element(el)

    # Strip children of <time> that are empty relative timestamps
    # (e.g. "Updated  ago" where the actual duration was JS-rendered).
    for el in list(content.iter("time")):
        for child in list(el):
            text = (child.text_content() or "").strip()
            if EMPTY_RELATIVE_TIME_RE.match(text):
                remove_element(child)

    # Chinese editorial chrome (【纠错】 error-correction button).
    for el in list(content.iter()):
        if not isinstance(el, HtmlElement):
            continue
        text = (el.text_content() or "").strip()
        if text and CN_EDITORIAL_RE.match(text) and el.getparent() is not None:
            remove_element(el)

    # Unwrap role="tablist" elements — tab navigation chrome, not content.
    # Unwrap inner <li> first so "Summary" becomes plain text, then the <ul>.
    for ul in list(content.iter("ul")):
        if ul.get("role") != "tablist":
            continue
        for li in list(ul.iter("li")):
            if li.getparent() is not None:
                unwrap(li)
        if ul.getparent() is not None:
            unwrap(ul)




def space_time_children(content: HtmlElement) -> None:
    """Add spaces between adjacent children of ``<time>`` elements.

    News sites often render dates as separate ``<span>`` children inside
    a ``<time>`` element with CSS spacing.  Without whitespace between
    them, text extraction concatenates e.g. "2026" and "9:45 AM" into
    "20269:45 AM".
    """
    for time_el in content.iter("time"):
        for child in time_el:
            if not isinstance(child.tag, str):
                continue
            if child.getnext() is None:
                continue
            if not child.tail:
                child.tail = " "


def drop_reply_posts(content: HtmlElement) -> None:
    """Keep only the first forum-post container; remove subsequent replies.

    Forum pages wrap the original post and every reply in identical
    containers (e.g. ``<div class="post">``).  After noise removal,
    if multiple "post" containers remain, keep only the first one
    and drop the rest.
    """
    posts: list[HtmlElement] = []
    for el in content.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag not in ("div", "article"):
            continue
        classes = el_classes(el)
        if any(POST_CLASS_RE.search(cls) for cls in classes):
            posts.append(el)

    if len(posts) > 1:
        for post in posts[1:]:
            remove_element(post)


def normalize_code_blocks(content: HtmlElement) -> None:
    """Convert Sphinx/Pygments code blocks to ``<pre><code>``.

    Sphinx renders highlighted code as::

        <div class="highlight-python …">
          <div class="highlight">
            <pre>…spans…</pre>
          </div>
        </div>

    This rewrites each to ``<pre><code class="language-python">``
    so that ``html-to-markdown`` emits fenced code blocks with a
    language tag.
    """
    from lxml.html import Element

    for outer in list(content.iter("div")):
        classes = (outer.get("class") or "").split()
        lang = ""
        for cls in classes:
            if cls.startswith("highlight-"):
                lang = cls[len("highlight-"):]
                break
        if not lang:
            continue

        pre = outer.find(".//pre")
        if pre is None:
            continue

        code = Element("code")
        code.set("class", f"language-{lang}")
        code.text = pre.text_content()

        new_pre = Element("pre")
        new_pre.append(code)
        new_pre.tail = outer.tail

        parent = outer.getparent()
        if parent is not None:
            parent.replace(outer, new_pre)


def replace_video_elements(content: HtmlElement) -> None:
    """Replace ``<video>`` elements with a linked poster image.

    Converts each ``<video>`` to ``<a href="…"><img …></a>``
    wrapped in a ``<p>`` so that the poster thumbnail is preserved
    and links to the video source.  If the video lives inside a
    ``<figure>``, the entire figure is replaced with the ``<p>``
    (including any ``<figcaption>`` text).
    """
    from lxml.html import Element

    for video in list(content.iter("video")):
        poster = video.get("poster", "")
        src = ""
        for source in video.iter("source"):
            src = source.get("src", "")
            if src:
                break

        if not src and not poster:
            remove_element(video)
            continue

        parent = video.getparent()
        if parent is None:
            continue

        link = Element("a")
        link.set("href", src or poster)
        if poster:
            img = Element("img")
            img.set("src", poster)
            img.set("alt", "video")
            link.append(img)
        else:
            link.text = "(video)"

        # Find the outermost <figure> wrapper, if any.
        fig = parent if parent.tag == "figure" else None
        if fig is None:
            gp = parent.getparent()
            if gp is not None and gp.tag == "figure":
                fig = gp

        if fig is not None:
            # Collect figcaption text.
            cap = fig.find(".//figcaption")
            caption = ""
            if cap is not None:
                caption = (cap.text_content() or "").strip()

            wrapper = Element("p")
            wrapper.append(link)
            if caption:
                link.tail = caption
            wrapper.tail = fig.tail
            fig.getparent().replace(fig, wrapper)
        else:
            link.tail = video.tail
            parent.replace(video, link)


def replace_audio_elements(content: HtmlElement) -> None:
    """Replace ``<audio>`` elements with a text link to the audio source.

    Converts each ``<audio>`` to ``<a href="…">(audio)</a>`` wrapped
    in a ``<p>``.  If the audio lives inside a ``<figure>``, the
    entire figure is replaced (including any ``<figcaption>`` text).
    Audio elements with no discoverable ``src`` are removed.
    """
    from lxml.html import Element

    for audio in list(content.iter("audio")):
        src = audio.get("src", "")
        if not src:
            for source in audio.iter("source"):
                src = source.get("src", "")
                if src:
                    break

        if not src:
            remove_element(audio)
            continue

        parent = audio.getparent()
        if parent is None:
            continue

        link = Element("a")
        link.set("href", src)
        link.text = "(audio)"

        fig = parent if parent.tag == "figure" else None
        if fig is None:
            gp = parent.getparent()
            if gp is not None and gp.tag == "figure":
                fig = gp

        if fig is not None:
            cap = fig.find(".//figcaption")
            caption = ""
            if cap is not None:
                caption = (cap.text_content() or "").strip()

            wrapper = Element("p")
            wrapper.append(link)
            if caption:
                link.tail = caption
            wrapper.tail = fig.tail
            fig.getparent().replace(fig, wrapper)
        else:
            link.tail = audio.tail
            parent.replace(audio, link)


def unwrap_links(content: HtmlElement) -> None:
    """Unwrap non-image ``<a>`` tags (keep link text, drop the tag)."""
    links = list(content.iter("a"))
    for el in links:
        if el.getparent() is None:
            continue
        href = el.get("href", "")
        if href and is_image_href(href):
            continue
        unwrap(el)


# ---------------------------------------------------------------------------
# PageCleaner – main sanitisation pipeline
# ---------------------------------------------------------------------------
class PageCleaner:
    """Clean an HTML DOM tree, extracting the main content subtree.

    Usage::

        cleaner = make_cleaner(meta)
        meta, content = cleaner.clean(tree)
    """

    def __init__(self, meta: PageMeta, *, skip_social: bool = False) -> None:
        """Initialise the cleaner with page metadata."""
        self._meta = meta
        self._skip_social = skip_social

    # -- public API --------------------------------------------------------

    def clean(self, tree: HtmlElement) -> tuple[PageMeta, HtmlElement]:
        """Run the full cleaning pipeline.

        Returns ``(page_meta, content_element)``.

        Pipeline:
          1. Strip HTML comments and ``<script>``/``<style>``/``<noscript>``
             tags.
          2. **Content-area identification** – try tiered XPath expressions
             to locate the main content container and narrow the tree.
          3. Normalise code blocks (Sphinx/Pygments → ``<pre><code>``).
          4. Remove remaining unwanted elements (ads, nav chrome, social
             links, …) from the content subtree.
          5. Forum reply de-duplication.
          6. Unwrap non-image ``<a>`` tags (keep link text, drop the tag).
        """
        self._tree = tree
        self._strip_comments_and_scripts()
        content = self._find_content_area()
        normalize_code_blocks(content)
        remove_noise(content, skip_social=self._skip_social)
        space_time_children(content)
        drop_reply_posts(content)
        unwrap_links(content)
        upgrade_src_from_srcset(content)
        return self._meta, content

    # -- private pipeline steps --------------------------------------------

    def _strip_comments_and_scripts(self) -> None:
        """Pass 1: remove comments + script/style/noscript."""
        for comment in self._tree.iter(etree.Comment):
            remove_element(comment)
        for tag_name in EARLY_STRIP_TAGS:
            for el in self._tree.xpath(f".//{tag_name}"):
                remove_element(el)

    def _find_content_area(self) -> HtmlElement:
        """Pass 2: locate the main content container via tiered XPath.

        Iterates through ``CONTENT_XPATH`` from most specific to
        broadest.  The first match with at least
        ``MIN_CONTENT_LENGTH`` characters of visible text is returned.
        Falls back to ``<body>`` then the tree root.
        """
        for tier in CONTENT_XPATH:
            for xpath in tier:
                try:
                    matches = self._tree.xpath(xpath)
                except etree.XPathError:
                    continue
                for candidate in matches:
                    if not isinstance(candidate, HtmlElement):
                        continue
                    text = (candidate.text_content() or "").strip()
                    if len(text) >= MIN_CONTENT_LENGTH:
                        return candidate

        # No XPath matched – fall back to <body> if present.
        bodies = self._tree.xpath(".//body")
        if bodies:
            return bodies[0]
        return self._tree


# ---------------------------------------------------------------------------
# Strip non-content tags – keep only basic formatting elements
# ---------------------------------------------------------------------------
# Tags whose semantics map directly to Markdown or are needed to
# preserve document structure.  Everything else is unwrapped (children
# and text kept, wrapping element removed).

# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------
def resolve_relative_urls(tree: HtmlElement, base_url: str) -> None:
    """Rewrite relative URLs in *tree* to absolute using *base_url*.

    Resolves ``src``, ``href``, and ``srcset`` attributes.  Skips
    values that already look absolute (``http(s)://``, ``data:``,
    ``mailto:``, ``#`` anchors, etc.).
    """
    if not base_url:
        return
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in URL_ATTRS:
            val = el.get(attr)
            if val is None:
                continue
            if attr == "srcset":
                el.set(attr, resolve_srcset(val, base_url))
            elif is_relative(val):
                el.set(attr, urljoin(base_url, val))


def is_relative(url: str) -> bool:
    """Return *True* if *url* looks relative (needs resolution)."""
    skip = ("#", "data:", "mailto:", "tel:", "javascript:")
    if not url or url.startswith(skip):
        return False
    return not url.startswith(("http://", "https://", "//"))


def resolve_srcset(srcset: str, base_url: str) -> str:
    """Resolve each URL in a ``srcset`` attribute value."""
    parts: list[str] = []
    for entry in srcset.split(","):
        entry = entry.strip()
        if not entry:
            continue
        tokens = entry.split(None, 1)
        url = tokens[0]
        descriptor = tokens[1] if len(tokens) > 1 else ""
        if is_relative(url):
            url = urljoin(base_url, url)
        parts.append(f"{url} {descriptor}".strip())
    return ", ".join(parts)


def upgrade_src_from_srcset(tree: HtmlElement) -> None:
    """Replace ``src`` with the best URL from ``srcset`` when available.

    Parses each ``srcset`` entry (e.g. ``"image-600.jpg 600w"``) and
    selects the variant with the largest width descriptor.  When no
    width descriptor is present the first entry is used as a fallback.

    This ensures Markdown ``![](...)`` embeds use a high-quality URL,
    and works around cases where ``src`` points to an unreachable
    ``http://`` URL while ``srcset`` contains a working ``https://``
    alternative.
    """
    for img in tree.iter("img"):
        srcset = img.get("srcset")
        if not srcset:
            continue
        best_url: str | None = None
        best_w = 0
        for entry in srcset.split(","):
            entry = entry.strip()
            if not entry:
                continue
            tokens = entry.split(None, 1)
            url = tokens[0]
            w = 0
            if len(tokens) > 1:
                desc = tokens[1].strip()
                if desc.endswith("w"):
                    with contextlib.suppress(ValueError):
                        w = int(desc[:-1])
            if w > best_w or (best_url is None):
                best_url = url
                best_w = w
        if best_url:
            img.set("src", best_url)


# ---------------------------------------------------------------------------
# Local media URL rewriting
# ---------------------------------------------------------------------------
def rewrite_media_urls(
    tree: HtmlElement, media_map: dict[str, str],
) -> None:
    """Replace remote media URLs with local paths using *media_map*.

    *media_map* maps original absolute URLs to local filenames
    inside the ``media/`` directory.

    Rewrites ``src``, ``poster``, and ``srcset`` attributes when the URL
    is present in the map.  Should be called **after**
    ``resolve_relative_urls`` so that URLs are already absolute.
    """
    rewrite_attrs = ("src", "poster")
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in rewrite_attrs:
            val = el.get(attr)
            if val and val in media_map:
                el.set(attr, f"media/{media_map[val]}")
        srcset = el.get("srcset")
        if srcset:
            parts: list[str] = []
            for entry in srcset.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                tokens = entry.split(None, 1)
                url = tokens[0]
                descriptor = tokens[1] if len(tokens) > 1 else ""
                if url in media_map:
                    url = f"media/{media_map[url]}"
                parts.append(f"{url} {descriptor}".strip())
            el.set("srcset", ", ".join(parts))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def make_cleaner(meta: PageMeta) -> PageCleaner:
    """Return the appropriate cleaner based on page metadata.

    Inspects ``meta.url`` to detect wiki pages and returns a
    :class:`WikiCleaner` for those.  Falls back to the base
    :class:`PageCleaner` otherwise.
    """
    if meta and meta.is_wiki:
        from .wiki import WikiCleaner

        return WikiCleaner(meta)
    return PageCleaner(meta)

