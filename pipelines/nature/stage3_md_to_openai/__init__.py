"""Map wiki markdown rows to OpenAI-style role-based messages in ``data``."""

from __future__ import annotations

import json
import re
from typing import Any

from dcd_cli.pipe import MultimodalBatch, PipeContext
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

FRONT_MATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n+)?",
)


def _strip_front_matter(md: str) -> str:
    """Remove a leading YAML front matter block when present."""
    if not md.startswith("---"):
        return md
    match = FRONT_MATTER_RE.match(md)
    if not match:
        return md
    return md[match.end() :]


def _parse_local_image_id(href: str) -> str | None:
    href = _parse_markdown_link_destination(href)
    if href.startswith("./"):
        href = href[2:]
    if not href.startswith("images/"):
        return None
    rest = href[len("images/") :]
    rest = rest.split("?", 1)[0].split("#", 1)[0].strip("/")
    return rest or None


def _parse_markdown_link_destination(href: str) -> str:
    """Return the Markdown link destination, excluding any optional title."""
    href = href.strip()
    if href.startswith("<"):
        close_idx = href.find(">")
        if close_idx > 0:
            return href[1:close_idx].strip()

    escaped = False
    for idx, ch in enumerate(href):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch.isspace():
            return href[:idx]
    return href


def _merge_adjacent_text(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in items:
        if item.get("type") != "text":
            merged.append(item)
            continue
        text = str(item.get("text", ""))
        if merged and merged[-1].get("type") == "text":
            merged[-1]["text"] = str(merged[-1].get("text", "")) + text
        else:
            merged.append({"type": "text", "text": text})
    return merged


def _append_local_image_part(parts: list[dict[str, Any]], image_id: str) -> None:
    parts.append(
        {
            "type": "image_url",
            "image_url": {"url": f"images/{image_id}"},
        },
    )


def _find_matching_paren(text: str, open_idx: int) -> int | None:
    depth = 0
    for idx in range(open_idx, len(text)):
        ch = text[idx]
        if ch == "\\":
            continue
        if ch == "(":
            depth += 1
            continue
        if ch != ")":
            continue
        depth -= 1
        if depth == 0:
            return idx
    return None


def _parse_plain_image_token(md: str, start: int) -> tuple[int, str] | None:
    if not md.startswith("![", start):
        return None
    alt_end = md.find("]", start + 2)
    if alt_end < 0 or alt_end + 1 >= len(md) or md[alt_end + 1] != "(":
        return None
    href_end = _find_matching_paren(md, alt_end + 1)
    if href_end is None:
        return None
    href = md[alt_end + 2 : href_end]
    return (href_end + 1, href)


def _parse_image_token(md: str, start: int) -> tuple[int, str] | None:
    if md.startswith("[![", start):
        inner = _parse_plain_image_token(md, start + 1)
        if inner is None:
            return None
        inner_end, href = inner
        if inner_end >= len(md) or md[inner_end] != "]":
            return None
        outer_paren_idx = inner_end + 1
        if outer_paren_idx >= len(md) or md[outer_paren_idx] != "(":
            return None
        outer_end = _find_matching_paren(md, outer_paren_idx)
        if outer_end is None:
            return None
        return (outer_end + 1, href)
    return _parse_plain_image_token(md, start)


def _find_next_image_token(md: str, start: int) -> tuple[int, int, str] | None:
    pos = start
    while pos < len(md):
        plain_idx = md.find("![", pos)
        wrapped_idx = md.find("[![", pos)
        candidates = [idx for idx in (plain_idx, wrapped_idx) if idx >= 0]
        if not candidates:
            return None
        match_start = min(candidates)
        token = _parse_image_token(md, match_start)
        if token is not None:
            match_end, href = token
            return (match_start, match_end, href)
        pos = match_start + 1
    return None


def _md_to_openai_content_parts(md: str) -> tuple[list[dict[str, Any]], int]:
    """Split markdown into OpenAI content parts and count dropped non-local images."""
    if not md:
        return ([{"type": "text", "text": ""}], 0)

    md = _strip_front_matter(md)
    if not md:
        return ([{"type": "text", "text": ""}], 0)

    parts: list[dict[str, Any]] = []
    dropped_nonlocal = 0
    pos = 0
    while True:
        token = _find_next_image_token(md, pos)
        if token is None:
            break
        match_start, match_end, href = token
        prefix = md[pos:match_start]
        if prefix:
            parts.append({"type": "text", "text": prefix})

        image_id = _parse_local_image_id(href)
        pos = match_end
        if image_id is None:
            dropped_nonlocal += 1
            continue

        _append_local_image_part(parts, image_id)

    tail = md[pos:]
    if tail:
        parts.append({"type": "text", "text": tail})

    if not parts:
        return ([{"type": "text", "text": ""}], dropped_nonlocal)
    return (_merge_adjacent_text(parts), dropped_nonlocal)


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


def _text_batch_from_input(batch: dict[str, Any]) -> tuple[dict[str, list[Any]], bool]:
    text_batch = batch.get("text")
    if isinstance(text_batch, dict):
        return {str(key): list(value) for key, value in text_batch.items()}, True
    return {str(key): list(value) for key, value in batch.items()}, False


def _values_for_row(column: list[Any], row_idx: int) -> list[Any]:
    if row_idx >= len(column):
        return []
    value = column[row_idx]
    if isinstance(value, list):
        return value
    return [value]


def _label_values_for_row(
    column: list[Any],
    row_idx: int,
    *,
    linked_count: int,
    default: Any,
) -> list[Any]:
    if row_idx >= len(column):
        return [default for _ in range(linked_count)]
    value = column[row_idx]
    if not isinstance(value, list):
        return [value for _ in range(linked_count)]
    if linked_count == 1:
        if value and not all(isinstance(item, str) for item in value):
            return value
        return [value]
    if len(value) == linked_count:
        return value
    return [value for _ in range(linked_count)]


def _value_at(values: list[Any], idx: int, default: Any) -> Any:
    return values[idx] if idx < len(values) else default


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value in (None, ""):
        return []
    return [str(value)]


def _flatten_linked_image_batch(image_batch: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {
        "id": [],
        "image_bytes": [],
        "info": [],
        "data": [],
        "tags": [],
    }
    if not isinstance(image_batch, dict):
        return out

    ids_col = list(image_batch.get("id") or [])
    bytes_col = list(image_batch.get("image_bytes") or [])
    info_col = list(image_batch.get("info") or [])
    data_col = list(image_batch.get("data") or [])
    tags_col = list(image_batch.get("tags") or [])

    for row_idx in range(len(ids_col)):
        ids = _values_for_row(ids_col, row_idx)
        blobs = _values_for_row(bytes_col, row_idx)
        linked_count = len(ids)
        infos = _label_values_for_row(info_col, row_idx, linked_count=linked_count, default={})
        data_values = _label_values_for_row(data_col, row_idx, linked_count=linked_count, default={})
        tag_values = _label_values_for_row(tags_col, row_idx, linked_count=linked_count, default=[])

        for item_idx, item_id in enumerate(ids):
            blob = _value_at(blobs, item_idx, None)
            if not item_id or not isinstance(blob, (bytes, bytearray)) or not blob:
                continue
            out["id"].append(str(item_id))
            out["image_bytes"].append(bytes(blob))
            out["info"].append(_value_at(infos, item_idx, {}))
            out["data"].append(_value_at(data_values, item_idx, {}))
            out["tags"].append(_normalize_tags(_value_at(tag_values, item_idx, [])))

    return out


def map(batch: MultimodalBatch, ctx: PipeContext) -> MultimodalBatch:
    """Encode each markdown ``data`` cell as a top-level OpenAI message array."""
    config = _ctx_config(ctx)
    message_role = str(config.get("message_role", "user") or "user")
    text_batch, nested = _text_batch_from_input(batch)

    data_out: list[str] = []
    info_out: list[str] = []

    for i, (md_raw, info_raw) in enumerate(zip(text_batch["data"], text_batch["info"], strict=True)):
        md = md_raw or ""
        info_raw = info_raw or "{}"
        try:
            info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
        except json.JSONDecodeError:
            info = {}
        if not isinstance(info, dict):
            info = {}

        parts, dropped_nonlocal = _md_to_openai_content_parts(md)
        messages = [{"role": message_role, "content": parts}]
        data_out.append(json.dumps(messages, ensure_ascii=False))

        info["format"] = "openai"
        image_ids = _extract_image_ids(parts)
        _set_canonical_image_links(info, image_ids)
        if dropped_nonlocal:
            info["dropped_nonlocal_images"] = dropped_nonlocal
        else:
            info.pop("dropped_nonlocal_images", None)
        info.pop("filtered_small_images", None)
        info.pop("image_refs", None)
        info_out.append(json.dumps(info, ensure_ascii=False))
        _set_progress(ctx, i + 1)

    text_out = {**text_batch, "data": data_out, "info": info_out}
    if not nested:
        return text_out  # type: ignore[return-value]
    return {
        "text": text_out,
        "image": _flatten_linked_image_batch(batch.get("image")),
    }
