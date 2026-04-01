"""Collect raw HTML image URLs and match them to local image IDs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import lance
from dcd_cli.pipe import PipeContext

THUMB_SIZE_RE = re.compile(r"/thumb/(.*)/\d+px-[^/]+$")
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
IMG_SRC_RE = re.compile(r'(\bsrc=["\'])([^"\']+)(["\'])', re.IGNORECASE)


def normalize_url(url: str) -> str:
    """Strip protocol and normalize Wikimedia thumbnail URLs."""
    url = unquote(re.sub(r"^https?:", "", url).lstrip("/"))
    m = THUMB_SIZE_RE.search(url)
    if m:
        url = url[: m.start()] + "/" + m.group(1)
    return url


def _resolve_dataset_dir(ctx: PipeContext) -> Path | None:
    if ctx.dataset_dir is not None:
        return Path(ctx.dataset_dir)
    config = ctx.config or {}
    raw = config.get("dataset_dir", "")
    if not raw:
        return None
    return Path(str(raw))


def _extract_html_image_urls(html: str) -> list[str]:
    urls: list[str] = []
    for match in IMG_TAG_RE.finditer(html):
        tag = match.group(0)
        src_match = IMG_SRC_RE.search(tag)
        if src_match:
            urls.append(src_match.group(2))
    return urls


def _load_image_url_candidates(dataset_dir: Path) -> dict[str, list[str]]:
    labels_path = dataset_dir / "image_labels.lance"
    if not labels_path.is_dir():
        return {}

    ds = lance.dataset(str(labels_path))
    tbl = ds.to_table(columns=["id", "info"])
    ids = tbl.column("id").to_pylist()
    infos = tbl.column("info").to_pylist()
    out: dict[str, list[str]] = {}
    for image_id, info_raw in zip(ids, infos, strict=True):
        if not image_id or not info_raw:
            continue
        try:
            info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(info, dict):
            continue
        candidate_urls: list[str] = []
        for key in ("image_url_ori", "image_url"):
            value = info.get(key)
            if isinstance(value, str) and value:
                candidate_urls.append(value)
        if not candidate_urls:
            continue
        for candidate_url in candidate_urls:
            norm = normalize_url(candidate_url)
            bucket = out.setdefault(norm, [])
            image_id_str = str(image_id)
            if image_id_str not in bucket:
                bucket.append(image_id_str)
    return out


def _pick_image_id(
    candidates: list[str],
    preferred_image_ids: list[str],
) -> str | None:
    if not candidates:
        return None
    if preferred_image_ids:
        order = {image_id: idx for idx, image_id in enumerate(preferred_image_ids)}
        ranked = [cid for cid in candidates if cid in order]
        if ranked:
            ranked.sort(key=lambda cid: order[cid])
            return ranked[0]
    return candidates[0]


def map(batch: dict[str, list[Any]], ctx: PipeContext) -> dict[str, list[Any]]:
    """Collect HTML image URLs and write structured match info into text.info."""
    dataset_dir = _resolve_dataset_dir(ctx)
    url_candidates: dict[str, list[str]] = {}
    if dataset_dir is not None:
        url_candidates = _load_image_url_candidates(dataset_dir)

    info_out: list[str] = []
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

        preferred_image_ids = info.get("image_ids")
        if not isinstance(preferred_image_ids, list):
            preferred_image_ids = []
        preferred_image_ids = [str(image_id) for image_id in preferred_image_ids if image_id]

        urls = _extract_html_image_urls(html)
        html_images = []
        for image_url in urls:
            normalized_url = normalize_url(image_url)
            image_id = _pick_image_id(
                url_candidates.get(normalized_url, []),
                preferred_image_ids,
            )
            html_images.append({
                "image_url_raw": image_url,
                "image_url_normalized": normalized_url,
                "matched": image_id is not None,
                "matched_image_id": image_id,
            })

        info["html_images"] = html_images
        info_out.append(json.dumps(info, ensure_ascii=False))
        ctx.set_progress(i + 1)

    return {**batch, "info": info_out}
