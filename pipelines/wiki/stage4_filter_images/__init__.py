"""Filter OpenAI image blocks by image label metadata from the input batch."""

from __future__ import annotations

import json
from typing import Any

from dcd_cli.pipe import Batch, MultimodalBatch, PipeContext


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


def _label_info_from_label_data(raw: Any) -> tuple[str | None, dict[str, Any]]:
    label = _parse_json_obj(raw)
    image_id = label.get("id")
    info = label.get("info")
    if info is not None:
        return (str(image_id) if image_id else None, _parse_json_obj(info))
    return (str(image_id) if image_id else None, label)


def _build_image_size_index(
    label_data: list[Any],
) -> dict[str, tuple[int, int]]:
    size_index: dict[str, tuple[int, int]] = {}
    for label_raw in label_data:
        image_id, info = _label_info_from_label_data(label_raw)
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


def map(
    batch: MultimodalBatch,
    ctx: PipeContext,
) -> Batch:
    """Filter local image blocks by width/height metadata from the input batch."""
    config = ctx.config or {}
    min_image_width = max(0, int(config.get("min_image_width", 0)))
    min_image_height = max(0, int(config.get("min_image_height", 0)))

    text_batch = batch["text"]
    image_sizes = _build_image_size_index(batch["image"]["label_data"])

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
            image_sizes=image_sizes,
            min_image_width=min_image_width,
            min_image_height=min_image_height,
        )
        data_out.append(_build_openai_payload(role, filtered_content))
        info["format"] = "openai"
        image_ids = _extract_image_ids(filtered_content)
        if image_ids:
            info["image_ids"] = image_ids
        else:
            info.pop("image_ids", None)
        if filtered_images:
            info["filtered_small_images"] = filtered_images
        else:
            info.pop("filtered_small_images", None)
        info_out.append(json.dumps(info, ensure_ascii=False))
        ctx.set_progress(i + 1)

    return {
        **text_batch,
        "data": data_out,
        "info": info_out,
    }
