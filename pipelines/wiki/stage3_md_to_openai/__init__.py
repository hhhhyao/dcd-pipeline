"""Map wiki markdown rows to OpenAI-style role-based messages in ``data``."""

from __future__ import annotations

import json
import re
from typing import Any

from dcd_cli.pipe import PipeContext

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
    href = href.strip()
    if href.startswith("./"):
        href = href[2:]
    if not href.startswith("images/"):
        return None
    rest = href[len("images/") :]
    rest = rest.split("?", 1)[0].split("#", 1)[0].strip("/")
    return rest or None


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


def map(batch: dict[str, list[Any]], ctx: PipeContext) -> dict[str, list[Any]]:
    """Encode each markdown ``data`` cell as a top-level OpenAI message array."""
    config = ctx.config or {}
    message_role = str(config.get("message_role", "user") or "user")

    data_out: list[str] = []
    info_out: list[str] = []

    for i, (md_raw, info_raw) in enumerate(zip(batch["data"], batch["info"], strict=True)):
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
        if image_ids:
            info["image_ids"] = image_ids
        else:
            info.pop("image_ids", None)
        if dropped_nonlocal:
            info["dropped_nonlocal_images"] = dropped_nonlocal
        else:
            info.pop("dropped_nonlocal_images", None)
        info.pop("filtered_small_images", None)
        info_out.append(json.dumps(info, ensure_ascii=False))
        ctx.set_progress(i + 1)

    return {**batch, "data": data_out, "info": info_out}
