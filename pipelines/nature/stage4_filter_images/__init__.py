"""Filter OpenAI image blocks by image label metadata from the input batch."""

from __future__ import annotations

import json
from typing import Any

from dcd_cli.pipe import Batch, MultimodalBatch, PipeContext
try:
    from dcd_cli.pipe import set_links
except ImportError:  # pragma: no cover - compatibility with older local dcd package

    def set_links(info: dict[str, Any], modality: str, items: list[Any]) -> None:
        defined = info.setdefault("__defined__", {})
        if not isinstance(defined, dict):
            defined = {}
            info["__defined__"] = defined
        links = defined.setdefault("links", {})
        if not isinstance(links, dict):
            links = {}
            defined["links"] = links
        entries = [
            dict(item) if isinstance(item, dict) else {"id": str(item)}
            for item in items
            if item
        ]
        if entries:
            links[modality] = entries
        else:
            links.pop(modality, None)
            if not links:
                defined.pop("links", None)
                if not defined:
                    info.pop("__defined__", None)


def _parse_openai_payload(data_raw: Any) -> tuple[list[dict[str, Any]], str]:
    try:
        payload = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid OpenAI payload JSON") from exc
    if isinstance(payload, dict):
        payload = payload.get("messages")
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("Expected a single-message OpenAI payload")
    message = payload[0]
    if not isinstance(message, dict):
        raise ValueError("Expected message to be an object")
    role = str(message.get("role") or "user")
    content = message.get("content")
    if not isinstance(content, list):
        raise ValueError("Expected message content to be a list")
    blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            raise ValueError("Expected content blocks to be objects")
        blocks.append(block)
    return (blocks, role)


def _build_openai_payload(role: str, content: list[dict[str, Any]]) -> str:
    return json.dumps([{"role": role, "content": content}], ensure_ascii=False)


def _parse_local_image_id(href: str) -> str | None:
    href = href.strip()
    if href.startswith("./"):
        href = href[2:]
    if not href.startswith("images/"):
        return None
    rest = href[len("images/") :]
    rest = rest.split("?", 1)[0].split("#", 1)[0].strip("/")
    return rest or None


def _extract_image_ids(parts: list[dict[str, Any]]) -> list[str]:
    image_ids: list[str] = []
    for part in parts:
        if part.get("type") != "image_url":
            continue
        image_url = part.get("image_url")
        if not isinstance(image_url, dict):
            continue
        raw_url = image_url.get("url")
        if not isinstance(raw_url, str):
            continue
        image_id = _parse_local_image_id(raw_url)
        if image_id:
            image_ids.append(image_id)
    return image_ids


def _parse_json_obj(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _build_image_size_index(
    image_ids: list[Any],
    image_info: list[Any],
) -> dict[str, tuple[int, int]]:
    """Build an ``image_id -> (width, height)`` index for one text row.

    Follows the current multimodal runner contract: secondary image rows
    arrive as per-text-row list columns, with ``id`` implicitly present
    and ``info`` explicitly requested by the manifest.
    """
    size_index: dict[str, tuple[int, int]] = {}
    for idx, image_id_raw in enumerate(image_ids):
        info_raw = image_info[idx] if idx < len(image_info) else {}
        image_id = str(image_id_raw) if image_id_raw else None
        info = _parse_json_obj(info_raw)
        _add_image_size(size_index, image_id, info)
    return size_index


def _add_image_size(
    size_index: dict[str, tuple[int, int]],
    image_id: Any,
    info: dict[str, Any],
) -> None:
    if not image_id or not info:
        return
    width = info.get("width")
    height = info.get("height")
    try:
        width_i = int(width) if width is not None else 0
        height_i = int(height) if height is not None else 0
    except (TypeError, ValueError):
        return
    if width_i > 0 and height_i > 0:
        size_index[str(image_id)] = (width_i, height_i)


def _filter_content_by_size(
    content: list[dict[str, Any]],
    *,
    image_sizes: dict[str, tuple[int, int]],
    min_image_width: int,
    min_image_height: int,
) -> tuple[list[dict[str, Any]], int]:
    filtered_content: list[dict[str, Any]] = []
    filtered_images = 0
    for block in content:
        if block.get("type") != "image_url":
            filtered_content.append(block)
            continue
        image_url = block.get("image_url")
        if not isinstance(image_url, dict):
            filtered_content.append(block)
            continue
        raw_url = image_url.get("url")
        if not isinstance(raw_url, str):
            filtered_content.append(block)
            continue
        image_id = _parse_local_image_id(raw_url)
        if image_id is None:
            filtered_content.append(block)
            continue
        size = image_sizes.get(image_id)
        if size is None:
            filtered_content.append(block)
            continue
        width, height = size
        if width < min_image_width or height < min_image_height:
            filtered_images += 1
            continue
        filtered_content.append(block)
    return (filtered_content, filtered_images)


def _text_batch_from_input(batch: MultimodalBatch) -> Batch:
    text_batch = batch["text"] if "text" in batch else {
        key.split("/", 1)[1]: value
        for key, value in batch.items()
        if isinstance(key, str) and key.startswith("text/")
    }
    return {
        str(column): list(values)
        for column, values in text_batch.items()
    }


def _secondary_rows(
    raw: Any,
    row_count: int,
) -> list[list[Any]]:
    """Return the per-primary-row secondary lists from the current batch."""
    if row_count <= 0:
        return []
    if not isinstance(raw, list):
        return [[] for _ in range(row_count)]
    return [
        list(item) if isinstance(item, list) else []
        for item in raw[:row_count]
    ] + [[] for _ in range(max(0, row_count - len(raw)))]


def _image_sizes_per_row(
    batch: MultimodalBatch,
    row_count: int,
) -> list[dict[str, tuple[int, int]]]:
    if row_count <= 0:
        return []

    image_batch = batch.get("image", {})
    if not image_batch:
        image_batch = {
            key.split("/", 1)[1]: value
            for key, value in batch.items()
            if isinstance(key, str) and key.startswith("image/")
        }
    if not isinstance(image_batch, dict):
        return [{} for _ in range(row_count)]

    image_ids_rows = _secondary_rows(image_batch.get("id"), row_count)
    image_info_rows = _secondary_rows(image_batch.get("info"), row_count)

    return [
        _build_image_size_index(
            image_ids_rows[i] if i < len(image_ids_rows) else [],
            image_info_rows[i] if i < len(image_info_rows) else [],
        )
        for i in range(row_count)
    ]


def _set_canonical_image_links(info: dict[str, Any], image_ids: list[str]) -> None:
    info.pop("image_ids", None)
    _apply_links(info, "images", image_ids)
    _apply_links(info, "image", image_ids)


def _apply_links(info: dict[str, Any], modality: str, items: list[Any]) -> None:
    updated = set_links(info, modality, items)
    if isinstance(updated, dict) and updated is not info:
        info.clear()
        info.update(updated)


def _ctx_config(ctx: PipeContext) -> dict[str, Any]:
    config = getattr(ctx, "config", None)
    if config is None:
        inputs = getattr(ctx, "inputs", None)
        config = getattr(inputs, "config", None) if inputs is not None else None
    return config if isinstance(config, dict) else {}


def _set_progress(ctx: PipeContext, completed: int) -> None:
    reporter = getattr(ctx, "reporter", None)
    set_progress = getattr(reporter, "set_progress", None)
    if callable(set_progress):
        set_progress(completed, 0, "")
        return
    set_progress = getattr(ctx, "set_progress", None)
    if callable(set_progress):
        set_progress(completed)


def map(
    batch: MultimodalBatch,
    ctx: PipeContext,
) -> Batch:
    """Filter local image blocks by width/height metadata from the input batch."""
    config = _ctx_config(ctx)
    min_image_width = max(0, int(config.get("min_image_width", 0)))
    min_image_height = max(0, int(config.get("min_image_height", 0)))

    text_batch = _text_batch_from_input(batch)
    row_count = len(text_batch.get("data", []))
    image_sizes_per_row = _image_sizes_per_row(batch, row_count)

    data_out: list[str] = []
    info_out: list[str] = []

    for i, (data_raw, info_raw) in enumerate(
        zip(text_batch["data"], text_batch["info"], strict=True),
    ):
        info_raw = info_raw or "{}"
        try:
            info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
        except json.JSONDecodeError:
            info = {}
        if not isinstance(info, dict):
            info = {}

        content, role = _parse_openai_payload(data_raw)
        filtered_content, filtered_images = _filter_content_by_size(
            content,
            image_sizes=image_sizes_per_row[i] if i < len(image_sizes_per_row) else {},
            min_image_width=min_image_width,
            min_image_height=min_image_height,
        )
        data_out.append(_build_openai_payload(role, filtered_content))
        info["format"] = "openai"
        image_ids = _extract_image_ids(filtered_content)
        _set_canonical_image_links(info, image_ids)
        if filtered_images:
            info["filtered_small_images"] = filtered_images
        else:
            info.pop("filtered_small_images", None)
        info_out.append(json.dumps(info, ensure_ascii=False))
        _set_progress(ctx, i + 1)

    return {
        **text_batch,
        "data": data_out,
        "info": info_out,
    }
