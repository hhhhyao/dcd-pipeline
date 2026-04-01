"""Map wiki markdown rows to OpenAI-style role-based messages in ``data``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import lance
from dcd_cli.pipe import PipeContext

FRONT_MATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n+)?",
)


def _resolve_dataset_dir(ctx: PipeContext) -> Path | None:
    if ctx.dataset_dir is not None:
        return Path(ctx.dataset_dir)
    cfg = ctx.config or {}
    raw = cfg.get("dataset_dir", "")
    if not raw:
        return None
    return Path(str(raw))


def _load_label_sizes(dataset_dir: Path) -> dict[str, tuple[int, int]]:
    """Read width/height from image_labels.lance ``info`` JSON when present."""
    labels_path = dataset_dir / "image_labels.lance"
    if not labels_path.is_dir():
        return {}

    ds = lance.dataset(str(labels_path))
    tbl = ds.to_table(columns=["id", "info"])
    ids = tbl.column("id").to_pylist()
    infos = tbl.column("info").to_pylist()
    out: dict[str, tuple[int, int]] = {}
    for image_id, info_raw in zip(ids, infos, strict=True):
        if not image_id or not info_raw:
            continue
        try:
            info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(info, dict):
            continue
        w = info.get("width")
        h = info.get("height")
        try:
            wi = int(w) if w is not None else 0
            hi = int(h) if h is not None else 0
        except (TypeError, ValueError):
            continue
        if wi > 0 and hi > 0:
            out[str(image_id)] = (wi, hi)
    return out


def _strip_front_matter(md: str) -> str:
    """Remove a leading YAML front matter block when present."""
    if not md.startswith("---"):
        return md
    m = FRONT_MATTER_RE.match(md)
    if not m:
        return md
    return md[m.end() :]


def _parse_local_image_id(href: str) -> str | None:
    href = href.strip()
    if href.startswith("./"):
        href = href[2:]
    if not href.startswith("images/"):
        return None
    rest = href[len("images/") :]
    rest = rest.split("?", 1)[0].split("#", 1)[0].strip("/")
    if rest:
        return rest
    return None


def _image_area(
    image_id: str,
    *,
    label_sizes: dict[str, tuple[int, int]],
) -> int | None:
    if image_id in label_sizes:
        w, h = label_sizes[image_id]
        return w * h
    return None


def _merge_adjacent_text(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for it in items:
        if it.get("type") != "text":
            merged.append(it)
            continue
        text = it.get("text", "")
        if merged and merged[-1].get("type") == "text":
            merged[-1]["text"] = str(merged[-1].get("text", "")) + str(text)
        else:
            merged.append({"type": "text", "text": str(text)})
    return merged


def _append_local_image_part(
    parts: list[dict[str, Any]],
    image_id: str,
    *,
    max_small_area: int,
    label_sizes: dict[str, tuple[int, int]],
) -> int:
    area = _image_area(
        image_id,
        label_sizes=label_sizes,
    )
    if area is not None and area <= max_small_area:
        return 1

    parts.append(
        {
            "type": "image_url",
            "image_url": {"url": f"images/{image_id}"},
        },
    )
    return 0


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


def _parse_plain_image_token(
    md: str,
    start: int,
) -> tuple[int, str] | None:
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


def _parse_image_token(
    md: str,
    start: int,
) -> tuple[int, str] | None:
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


def _find_next_image_token(
    md: str,
    start: int,
) -> tuple[int, int, str] | None:
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


def _md_to_openai_content_parts(
    md: str,
    *,
    max_small_area: int,
    label_sizes: dict[str, tuple[int, int]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Split markdown into OpenAI content parts; return parts + filter/drop counts."""
    if not md:
        return ([{"type": "text", "text": ""}], 0, 0)

    md = _strip_front_matter(md)
    if not md:
        return ([{"type": "text", "text": ""}], 0, 0)

    parts: list[dict[str, Any]] = []
    filtered = 0
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

        filtered += _append_local_image_part(
            parts,
            image_id,
            max_small_area=max_small_area,
            label_sizes=label_sizes,
        )

    tail = md[pos:]
    if tail:
        parts.append({"type": "text", "text": tail})

    if not parts:
        return ([{"type": "text", "text": ""}], filtered, dropped_nonlocal)

    merged = _merge_adjacent_text(parts)
    return (merged, filtered, dropped_nonlocal)


def map(batch: dict[str, list[Any]], ctx: PipeContext) -> dict[str, list[Any]]:
    """Encode each markdown ``data`` cell as OpenAI-style ``messages`` JSON."""
    config = ctx.config or {}
    max_small_area = int(config.get("max_small_area", 784))
    message_role = str(config.get("message_role", "user") or "user")

    dataset_dir = _resolve_dataset_dir(ctx)
    label_sizes: dict[str, tuple[int, int]] = {}
    if dataset_dir is not None:
        label_sizes = _load_label_sizes(dataset_dir)

    data_out: list[str] = []
    info_out: list[str] = []

    for i, (md_raw, info_raw) in enumerate(
        zip(batch["data"], batch["info"], strict=True),
    ):
        md = md_raw or ""
        info_raw = info_raw or "{}"
        try:
            info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
        except json.JSONDecodeError:
            info = {}
        if not isinstance(info, dict):
            info = {}

        parts, n_filtered, n_dropped_nonlocal = _md_to_openai_content_parts(
            md,
            max_small_area=max_small_area,
            label_sizes=label_sizes,
        )
        messages = [{"role": message_role, "content": parts}]
        data_out.append(
            json.dumps({"messages": messages}, ensure_ascii=False),
        )
        info["format"] = "openai"
        if n_filtered:
            info["filtered_small_images"] = n_filtered
        else:
            info.pop("filtered_small_images", None)
        if n_dropped_nonlocal:
            info["dropped_nonlocal_images"] = n_dropped_nonlocal
        else:
            info.pop("dropped_nonlocal_images", None)
        info_out.append(json.dumps(info, ensure_ascii=False))
        ctx.set_progress(i + 1)

    return {**batch, "data": data_out, "info": info_out}
