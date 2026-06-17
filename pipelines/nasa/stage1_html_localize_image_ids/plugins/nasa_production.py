"""NASA-specific HTML image extraction, normalization, and rewriting."""

from __future__ import annotations

import html
import re
from collections import deque
from urllib.parse import unquote, urlparse


IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SRC_ATTR_RE = re.compile(
    r'(?P<prefix>\s)(?P<name>src|data-src|data-original|data-lazy-src)=["\'](?P<value>[^"\']+)["\']',
    re.IGNORECASE,
)
SRCSET_ATTR_RE = re.compile(
    r'(?P<prefix>\s)(?P<name>srcset|data-srcset|imagesrcset)=["\'](?P<value>[^"\']+)["\']',
    re.IGNORECASE,
)
REMOVE_LAZY_ATTR_RE = re.compile(
    r'\s(?:srcset|data-srcset|imagesrcset|data-src|data-original|data-lazy-src)=["\'][^"\']*["\']',
    re.IGNORECASE,
)


def _clean_url(url: str) -> str:
    return html.unescape(url or "").replace("\\/", "/").strip().strip("\"'")


def _parse_srcset(value: str) -> list[str]:
    urls: list[str] = []
    for part in value.split(","):
        part = _clean_url(part)
        if not part:
            continue
        urls.append(part.split()[0])
    return urls


def _first_img_candidate(tag: str) -> str | None:
    for match in SRC_ATTR_RE.finditer(tag):
        value = _clean_url(match.group("value"))
        if value:
            return value
    for match in SRCSET_ATTR_RE.finditer(tag):
        urls = _parse_srcset(match.group("value"))
        if urls:
            return urls[0]
    return None


def extract_img_urls_from_html(source_html: str) -> list[str]:
    """Extract one representative image URL from each ``<img>`` tag."""
    out: list[str] = []
    for tag_match in IMG_TAG_RE.finditer(source_html or ""):
        candidate = _first_img_candidate(tag_match.group(0))
        if candidate:
            out.append(candidate)
    return out


def normalize_image_url(url: str) -> str:
    """Normalize NASA image URLs for matching HTML attrs to text image_refs."""
    value = _clean_url(url)
    if not value:
        return ""

    if value.startswith("./"):
        value = value[2:]
    if value.startswith("assets/"):
        return f"nasa-asset/{unquote(value.removeprefix('assets/'))}"
    if value.startswith("/assets/"):
        return f"nasa-asset/{unquote(value.removeprefix('/assets/'))}"

    parsed = urlparse(value if not value.startswith("//") else f"https:{value}")
    path = parsed.path or ""

    host = parsed.netloc.lower()
    if not host and path.startswith("/"):
        host = "www.nasa.gov"
    elif not host and path.startswith("wp-content/"):
        host = "www.nasa.gov"
        path = f"/{path}"
    normalized = f"{host}{unquote(path)}"
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    return normalized.lstrip("/")


def format_image_ref(image_id: str, image_ref_id: str) -> dict[str, str]:
    """Format the dataset-local HTML image reference payload."""
    return {
        "src": f"images/{image_id}",
        "image_ref_id": image_ref_id,
    }


def _replace_or_insert_src(tag: str, src: str) -> str:
    if re.search(r'\ssrc=["\']', tag, flags=re.IGNORECASE):
        return re.sub(
            r'(\ssrc=["\'])[^"\']*(["\'])',
            rf"\g<1>{src}\g<2>",
            tag,
            count=1,
            flags=re.IGNORECASE,
        )
    return re.sub(r"\s*/?>$", lambda match: f' src="{src}"{match.group(0)}', tag, count=1)


def _set_image_ref_id(tag: str, image_ref_id: str) -> str:
    if "_image_ref_id=" in tag:
        return re.sub(
            r'(\s_image_ref_id=["\'])[^"\']*(["\'])',
            rf"\g<1>{image_ref_id}\g<2>",
            tag,
            count=1,
            flags=re.IGNORECASE,
        )
    return re.sub(
        r"\s*/?>$",
        lambda match: f' _image_ref_id="{image_ref_id}"{match.group(0)}',
        tag,
        count=1,
    )


def rewrite_html(source_html: str, replacements_by_raw_url: dict[str, list[dict[str, str] | None]]) -> str:
    """Rewrite matching ``<img>`` tags to local ``images/<id>`` references."""
    if not replacements_by_raw_url:
        return source_html

    replacement_queues = {
        raw_url: deque(replacements)
        for raw_url, replacements in replacements_by_raw_url.items()
    }
    out: list[str] = []
    cursor = 0

    for tag_match in IMG_TAG_RE.finditer(source_html):
        start, end = tag_match.span()
        tag = tag_match.group(0)
        raw_url = _first_img_candidate(tag)
        replacement = None
        if raw_url:
            queue = replacement_queues.get(raw_url)
            if queue:
                replacement = queue.popleft()

        if replacement is not None:
            tag = REMOVE_LAZY_ATTR_RE.sub("", tag)
            tag = _replace_or_insert_src(tag, replacement["src"])
            tag = _set_image_ref_id(tag, replacement["image_ref_id"])

        out.append(source_html[cursor:start])
        out.append(tag)
        cursor = end

    out.append(source_html[cursor:])
    return "".join(out)
