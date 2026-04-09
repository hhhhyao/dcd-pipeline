"""Wikimedia-specific HTML image extraction, normalization, and formatting."""

from __future__ import annotations

import re
from collections import deque
from urllib.parse import unquote


THUMB_SIZE_RE = re.compile(r"/thumb/(.*)/\d+px-[^/]+$")
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
IMG_SRC_RE = re.compile(r'(\bsrc=["\'])([^"\']+)(["\'])', re.IGNORECASE)
SRCSET_RE = re.compile(r'\s*\bsrcset=["\'][^"\']*["\']', re.IGNORECASE)


def _iter_img_src_matches(html: str):
    """Yield tag and src matches for ``<img src=...>`` in document order."""
    for tag_match in IMG_TAG_RE.finditer(html):
        tag = tag_match.group(0)
        src_match = IMG_SRC_RE.search(tag)
        if src_match:
            yield tag_match, src_match


def extract_img_urls_from_html(html: str) -> list[str]:
    """Extract raw ``src`` values from ``<img>`` tags in document order."""
    return [src_match.group(2) for _, src_match in _iter_img_src_matches(html)]


def normalize_image_url(url: str) -> str:
    """Normalize Wikimedia image URLs to a protocol-free canonical form."""
    normalized = unquote(re.sub(r"^https?:", "", url).lstrip("/"))
    match = THUMB_SIZE_RE.search(normalized)
    if match:
        normalized = normalized[: match.start()] + "/" + match.group(1)
    return normalized


def format_image_ref(image_id: str) -> str:
    """Format the dataset-local HTML image reference."""
    return f"images/{image_id}"


def rewrite_html(html: str, replacements_by_raw_url: dict[str, list[str | None]]) -> str:
    """Rewrite HTML ``img[src]`` values using per-raw-url replacement queues."""
    if not replacements_by_raw_url:
        return html

    replacement_queues = {
        raw_url: deque(replacements)
        for raw_url, replacements in replacements_by_raw_url.items()
    }
    out: list[str] = []
    cursor = 0

    for tag_match, src_match in _iter_img_src_matches(html):
        start, end = tag_match.span()
        tag = tag_match.group(0)
        raw_url = src_match.group(2)
        queue = replacement_queues.get(raw_url)
        if queue:
            replacement = queue.popleft()
            if replacement is not None:
                tag = SRCSET_RE.sub("", tag)
                tag = IMG_SRC_RE.sub(rf"\g<1>{replacement}\g<3>", tag, count=1)
        out.append(html[cursor:start])
        out.append(tag)
        cursor = end

    out.append(html[cursor:])
    return "".join(out)
