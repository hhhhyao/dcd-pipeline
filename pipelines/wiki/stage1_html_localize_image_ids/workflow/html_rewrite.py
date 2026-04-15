"""HTML URL matching and rewrite helpers."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

ExtractorFn = Callable[[str], list[str]]
NormalizerFn = Callable[[str], str]
ReplacementPayload = dict[str, str]
FormatterFn = Callable[[str, str], ReplacementPayload]
RewriterFn = Callable[[str, dict[str, list[ReplacementPayload | None]]], str]


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


def parse_image_ref_id(image_ref_id: str) -> tuple[str, str] | None:
    """Split ``image_ref_id`` into ``(image_id, image_url_ori_hash)``."""
    if not isinstance(image_ref_id, str) or "_" not in image_ref_id:
        return None
    image_id, image_url_ori_hash = image_ref_id.split("_", 1)
    if not image_id or not image_url_ori_hash:
        return None
    return image_id, image_url_ori_hash


def build_local_url_map(
    image_refs: dict[str, dict[str, Any]],
    normalize_url: NormalizerFn,
) -> tuple[dict[str, dict[str, str]], dict[str, list[str]], dict[str, list[str]]]:
    """Build normalized URL -> image ref payload for a single text row."""
    normalized_to_ref: dict[str, dict[str, str]] = {}
    raw_urls_by_ref_id: dict[str, list[str]] = {}
    normalized_urls_by_ref_id: dict[str, list[str]] = {}

    for image_ref_id, info in image_refs.items():
        parsed = parse_image_ref_id(image_ref_id)
        raw_url = info.get("image_url_ori") if isinstance(info, dict) else None
        raw_urls: list[str] = []
        normalized_urls: list[str] = []
        if isinstance(raw_url, str) and raw_url:
            raw_urls.append(raw_url)
            normalized = normalize_url(raw_url)
            if normalized:
                normalized_urls.append(normalized)
                if parsed is not None:
                    image_id, _ = parsed
                    normalized_to_ref.setdefault(normalized, {
                        "image_id": image_id,
                        "image_ref_id": image_ref_id,
                    })
        raw_urls_by_ref_id[image_ref_id] = dedupe_preserve_order(raw_urls)
        normalized_urls_by_ref_id[image_ref_id] = dedupe_preserve_order(normalized_urls)

    return normalized_to_ref, raw_urls_by_ref_id, normalized_urls_by_ref_id


def build_html_rewrite_plan(
    html: str,
    *,
    extract_urls: ExtractorFn,
    normalize_url: NormalizerFn,
    format_image_ref: FormatterFn,
    normalized_to_ref: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Build a source-of-truth rewrite plan from extractor-returned URLs."""
    missing: list[dict[str, str]] = []
    matched_normalized_urls: set[str] = set()
    used_image_ids: list[str] = []
    used_image_ref_ids: list[str] = []
    replacements_by_raw_url: dict[str, list[ReplacementPayload | None]] = {}
    for raw_url in extract_urls(html):
        normalized = normalize_url(raw_url)
        matched_ref = normalized_to_ref.get(normalized)
        if not matched_ref:
            missing.append({
                "image_url_raw": raw_url,
                "image_url_normalized": normalized,
            })
            replacements_by_raw_url.setdefault(raw_url, []).append(None)
            continue

        matched_normalized_urls.add(normalized)
        image_id = matched_ref["image_id"]
        image_ref_id = matched_ref["image_ref_id"]
        used_image_ids.append(image_id)
        used_image_ref_ids.append(image_ref_id)
        replacements_by_raw_url.setdefault(raw_url, []).append(format_image_ref(image_id, image_ref_id))

    return {
        "replacements_by_raw_url": replacements_by_raw_url,
        "missing_urls": missing,
        "matched_normalized_urls": matched_normalized_urls,
        "used_image_ids": used_image_ids,
        "used_image_ref_ids": used_image_ref_ids,
    }
