"""HTML URL matching and rewrite helpers."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

ExtractorFn = Callable[[str], list[str]]
NormalizerFn = Callable[[str], str]
FormatterFn = Callable[[str], str]
RewriterFn = Callable[[str, dict[str, list[str | None]]], str]


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    """Return unique values in their first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def json_dumps(value: Any) -> str:
    """Serialize JSON using UTF-8-friendly defaults."""
    return json.dumps(value, ensure_ascii=False)


def extract_candidate_urls_from_label_info(info: dict[str, Any]) -> list[str]:
    """Pull all matching candidate URLs from an image-label info dict."""
    out: list[str] = []
    for key in ("image_url_ori", "image_url"):
        value = info.get(key)
        if isinstance(value, str) and value:
            out.append(value)
    return dedupe_preserve_order(out)


def build_local_url_map(
    image_ids: list[str],
    image_label_infos: dict[str, list[dict[str, Any]]],
    normalize_url: NormalizerFn,
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]]:
    """Build normalized URL -> image ID for a single text row."""
    normalized_to_image_id: dict[str, str] = {}
    raw_urls_by_id: dict[str, list[str]] = {}
    normalized_urls_by_id: dict[str, list[str]] = {}

    for image_id in image_ids:
        raw_urls: list[str] = []
        normalized_urls: list[str] = []
        for info in image_label_infos.get(image_id, []):
            for raw_url in extract_candidate_urls_from_label_info(info):
                raw_urls.append(raw_url)
                normalized = normalize_url(raw_url)
                if not normalized:
                    continue
                normalized_urls.append(normalized)
                normalized_to_image_id.setdefault(normalized, image_id)
        raw_urls_by_id[image_id] = dedupe_preserve_order(raw_urls)
        normalized_urls_by_id[image_id] = dedupe_preserve_order(normalized_urls)

    return normalized_to_image_id, raw_urls_by_id, normalized_urls_by_id


def build_html_rewrite_plan(
    html: str,
    *,
    extract_urls: ExtractorFn,
    normalize_url: NormalizerFn,
    format_image_ref: FormatterFn,
    normalized_to_image_id: dict[str, str],
) -> dict[str, Any]:
    """Build a source-of-truth rewrite plan from extractor-returned URLs."""
    missing: list[dict[str, str]] = []
    matched_normalized_urls: set[str] = set()
    used_image_ids: list[str] = []
    replacements_by_raw_url: dict[str, list[str | None]] = {}
    for raw_url in extract_urls(html):
        normalized = normalize_url(raw_url)
        image_id = normalized_to_image_id.get(normalized)
        if not image_id:
            missing.append({
                "image_url_raw": raw_url,
                "image_url_normalized": normalized,
            })
            replacements_by_raw_url.setdefault(raw_url, []).append(None)
            continue

        matched_normalized_urls.add(normalized)
        used_image_ids.append(image_id)
        replacements_by_raw_url.setdefault(raw_url, []).append(format_image_ref(image_id))

    return {
        "replacements_by_raw_url": replacements_by_raw_url,
        "missing_urls": missing,
        "matched_normalized_urls": matched_normalized_urls,
        "used_image_ids": used_image_ids,
    }
