"""Temporarily localize HTML image URLs using already-known per-row image IDs."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import lance
from dcd_cli.pipe import PipeContext

THUMB_SIZE_RE = re.compile(r"/thumb/(.*)/\d+px-[^/]+$")
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
IMG_SRC_RE = re.compile(r'(\bsrc=["\'])([^"\']+)(["\'])', re.IGNORECASE)
SRCSET_RE = re.compile(r'\s*\bsrcset=["\'][^"\']*["\']', re.IGNORECASE)

LOGGER = logging.getLogger(__name__)
_IMAGE_ID_URLS_CACHE: dict[str, dict[str, list[str]]] = {}


def normalize_url(url: str) -> str:
    """Strip protocol and normalize Wikimedia thumbnail URLs."""
    url = unquote(re.sub(r"^https?:", "", url).lstrip("/"))
    match = THUMB_SIZE_RE.search(url)
    if match:
        url = url[: match.start()] + "/" + match.group(1)
    return url


def _dedup_strings(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _dedup_image_ids(image_ids: Iterable[str | None]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for image_id in image_ids:
        if not isinstance(image_id, str) or not image_id or image_id in seen:
            continue
        seen.add(image_id)
        out.append(image_id)
    return out


def _resolve_labels_path(ctx: PipeContext) -> tuple[str, Path] | None:
    dataset_name = str(getattr(ctx, "dataset", "") or "").strip()
    if dataset_name:
        labels_path = Path("/datasets") / dataset_name / "image_labels.lance"
        if labels_path.is_dir():
            return dataset_name, labels_path

    volumes = getattr(ctx, "volumes", None) or {}
    dataset_volume = volumes.get("dataset")
    if dataset_volume is not None:
        dataset_dir = Path(dataset_volume)
        labels_path = dataset_dir / "image_labels.lance"
        if labels_path.is_dir():
            cache_key = dataset_name or str(dataset_dir.resolve())
            return cache_key, labels_path

    dataset_dir = getattr(ctx, "dataset_dir", None)
    if dataset_dir is not None:
        labels_path = Path(dataset_dir) / "image_labels.lance"
        if labels_path.is_dir():
            cache_key = dataset_name or str(Path(dataset_dir).resolve())
            return cache_key, labels_path

    config = ctx.config or {}
    raw_dataset_dir = config.get("dataset_dir")
    if raw_dataset_dir:
        labels_path = Path(str(raw_dataset_dir)) / "image_labels.lance"
        if labels_path.is_dir():
            cache_key = dataset_name or str(Path(raw_dataset_dir).resolve())
            return cache_key, labels_path

    return None


def _load_image_id_to_urls(labels_path: Path) -> dict[str, list[str]]:
    ds = lance.dataset(str(labels_path))
    table = ds.to_table(columns=["id", "info"])
    image_ids = table.column("id").to_pylist()
    infos = table.column("info").to_pylist()

    image_id_to_urls: dict[str, list[str]] = {}
    for image_id, info_raw in zip(image_ids, infos, strict=True):
        if not image_id or not info_raw:
            continue
        try:
            info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(info, dict):
            continue

        candidates: list[str] = []
        for key in ("image_url_ori", "image_url", "url"):
            value = info.get(key)
            if isinstance(value, str) and value:
                candidates.append(normalize_url(value))

        deduped = _dedup_strings(candidates)
        if deduped:
            image_id_to_urls[str(image_id)] = deduped

    return image_id_to_urls


def _get_image_id_to_urls(ctx: PipeContext) -> dict[str, list[str]]:
    resolved = _resolve_labels_path(ctx)
    if resolved is None:
        LOGGER.warning(
            "stage1_5: unable to resolve image_labels.lance for dataset=%s",
            str(getattr(ctx, "dataset", "") or ""),
        )
        return {}

    cache_key, labels_path = resolved
    cached = _IMAGE_ID_URLS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    cached = _load_image_id_to_urls(labels_path)
    _IMAGE_ID_URLS_CACHE[cache_key] = cached
    return cached


def _build_match_map(
    image_ids: list[str],
    image_id_to_urls: dict[str, list[str]],
) -> tuple[dict[str, str], int]:
    raw_url_to_image_id: dict[str, str] = {}
    conflict_count = 0

    for image_id in image_ids:
        for raw_url in image_id_to_urls.get(image_id, []):
            existing = raw_url_to_image_id.get(raw_url)
            if existing is None:
                raw_url_to_image_id[raw_url] = image_id
                continue
            if existing != image_id:
                conflict_count += 1

    return raw_url_to_image_id, conflict_count


def _rewrite_html_with_match_map(
    html: str,
    raw_url_to_image_id: dict[str, str],
) -> tuple[str, list[str]]:
    used_image_ids: list[str] = []

    def replacer(match: re.Match[str]) -> str:
        tag = match.group(0)
        src_match = IMG_SRC_RE.search(tag)
        if not src_match:
            return tag

        current_src = src_match.group(2)
        image_id = raw_url_to_image_id.get(normalize_url(current_src))
        if not isinstance(image_id, str) or not image_id:
            return tag

        used_image_ids.append(image_id)
        tag = SRCSET_RE.sub("", tag)
        return IMG_SRC_RE.sub(rf"\g<1>images/{image_id}\g<3>", tag)

    return IMG_TAG_RE.sub(replacer, html), used_image_ids


def map(batch: dict[str, list[Any]], ctx: PipeContext) -> dict[str, list[Any]]:
    """Localize HTML image URLs using only image IDs already present on each row."""
    image_id_to_urls = _get_image_id_to_urls(ctx)
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

        raw_image_ids = info.get("image_ids")
        image_ids = (
            [str(image_id) for image_id in raw_image_ids if image_id]
            if isinstance(raw_image_ids, list)
            else []
        )
        raw_url_to_image_id, conflict_count = _build_match_map(
            image_ids,
            image_id_to_urls,
        )
        batch_conflict_count += conflict_count

        rewritten_html, used_image_ids = _rewrite_html_with_match_map(
            html,
            raw_url_to_image_id,
        )
        data_out.append(rewritten_html)

        localized_image_ids = _dedup_image_ids(used_image_ids)
        if localized_image_ids:
            info["image_ids"] = localized_image_ids
        else:
            info.pop("image_ids", None)
        info.pop("html_images", None)
        info["format"] = "html"
        info_out.append(json.dumps(info, ensure_ascii=False))
        ctx.set_progress(i + 1)

    if batch_conflict_count:
        LOGGER.warning(
            "stage1_5: detected %d per-row image URL conflict(s); kept the "
            "first image_id according to info.image_ids order.",
            batch_conflict_count,
        )

    return {**batch, "data": data_out, "info": info_out}
