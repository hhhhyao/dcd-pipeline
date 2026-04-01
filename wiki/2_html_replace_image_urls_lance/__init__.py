"""Rewrite raw HTML image URLs to local images/{id} using stored matches."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from typing import Any

from dcd_cli.pipe import PipeContext

IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
IMG_SRC_RE = re.compile(r'(\bsrc=["\'])([^"\']+)(["\'])', re.IGNORECASE)
SRCSET_RE = re.compile(r'\s*\bsrcset=["\'][^"\']*["\']', re.IGNORECASE)

LOGGER = logging.getLogger(__name__)


def _dedup_image_ids(image_ids: Iterable[str | None]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for image_id in image_ids:
        if not isinstance(image_id, str) or not image_id or image_id in seen:
            continue
        seen.add(image_id)
        out.append(image_id)
    return out


def _build_match_map(
    html_images: list[dict[str, Any]],
) -> tuple[dict[str, str | None], int]:
    raw_url_to_image_id: dict[str, str | None] = {}
    conflict_count = 0

    for entry in html_images:
        if not isinstance(entry, dict):
            continue
        raw_url = entry.get("image_url_raw")
        if not isinstance(raw_url, str) or not raw_url:
            continue
        image_id = entry.get("matched_image_id")
        if image_id is not None and not isinstance(image_id, str):
            image_id = None

        if raw_url in raw_url_to_image_id:
            if raw_url_to_image_id[raw_url] != image_id:
                conflict_count += 1
            continue
        raw_url_to_image_id[raw_url] = image_id

    return raw_url_to_image_id, conflict_count


def _rewrite_html_with_match_map(
    html: str,
    raw_url_to_image_id: dict[str, str | None],
) -> tuple[str, list[str]]:
    used_image_ids: list[str] = []

    def replacer(m: re.Match[str]) -> str:
        tag = m.group(0)
        src_match = IMG_SRC_RE.search(tag)
        if not src_match:
            return tag
        current_src = src_match.group(2)
        image_id = raw_url_to_image_id.get(current_src)
        if not isinstance(image_id, str) or not image_id:
            return tag

        used_image_ids.append(image_id)
        tag = SRCSET_RE.sub("", tag)
        return IMG_SRC_RE.sub(rf"\g<1>images/{image_id}\g<3>", tag)

    return IMG_TAG_RE.sub(replacer, html), used_image_ids


def map(batch: dict[str, list[Any]], ctx: PipeContext) -> dict[str, list[Any]]:
    """Rewrite HTML image src values using text.info.html_images."""
    data_out: list[str] = []
    info_out: list[str] = []
    batch_conflict_count = 0

    for i, (html_raw, info_raw) in enumerate(
        zip(batch["data"], batch["info"], strict=True),
    ):
        html = html_raw or ""
        info_raw = info_raw or "{}"
        try:
            info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
        except json.JSONDecodeError:
            info = {}
        if not isinstance(info, dict):
            info = {}

        raw_html_images = info.get("html_images")
        html_images = raw_html_images if isinstance(raw_html_images, list) else []
        raw_url_to_image_id, conflict_count = _build_match_map(html_images)
        batch_conflict_count += conflict_count
        rewritten, used_image_ids = _rewrite_html_with_match_map(
            html,
            raw_url_to_image_id,
        )
        data_out.append(rewritten)

        image_ids = _dedup_image_ids(used_image_ids)
        if image_ids:
            info["image_ids"] = image_ids
        else:
            info.pop("image_ids", None)
        info.pop("html_images", None)
        info["format"] = "html"
        info_out.append(json.dumps(info, ensure_ascii=False))
        ctx.set_progress(i + 1)

    if batch_conflict_count:
        LOGGER.warning(
            "Detected %d html_images raw-url conflict(s); stage2 kept the first "
            "matched_image_id for each raw URL and continued.",
            batch_conflict_count,
        )

    return {**batch, "data": data_out, "info": info_out}
